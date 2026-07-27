"""End-to-end fixture tests driving the full HTTP API against real sample images.

Real Tesseract and llama-cpp-python are unavailable in this sandbox (see tasks 3.2 and
5.1), so OCR and LLM extraction are faked -- but every other stage (image decode,
OpenCV shape classification, real QR decode via cv2.QRCodeDetector, reconciliation,
persistence to a real Postgres instance, and the full HTTP/routing/exception-handling
stack) runs for real, against real fixture image files on disk rather than in-memory
byte strings.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_card_processing_service
from app.db.card_repository import CardRepository
from app.db.session import get_db
from app.main import app
from app.schemas import ExtractedField, LlmExtractionResult
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.image_preprocessor import ImagePreprocessor
from app.services.image_storage.local_storage import LocalImageStorage
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_OCR_TEXT = "Jane Doe\nAcme Corp\njane@acme.com\n+1-555-0100"


class _FakeOcrService:
    def extract_text(self, image) -> str:
        return _OCR_TEXT


class _FakeLlmExtractionService:
    """Deliberately returns a company value ("Acme Corp") that differs from the
    QR fixture's payload ("Acme Corporation"), so the e2e test exercises a real
    field conflict produced by the actual reconciliation logic -- not a manually
    forced database state."""

    def extract(self, ocr_text: str) -> LlmExtractionResult:
        return LlmExtractionResult(
            name=ExtractedField(value="Jane Doe", confidence=0.95),
            position=ExtractedField(value=None, confidence=0.1),
            company=ExtractedField(value="Acme Corp", confidence=0.9),
            email=ExtractedField(value="jane@acme.com", confidence=0.99),
            phone=ExtractedField(value="+1-555-0100", confidence=0.9),
        )


@pytest.fixture
def client(db_session, tmp_path):
    def override_get_db():
        yield db_session

    def override_service():
        return CardProcessingService(
            image_preprocessor=ImagePreprocessor(),
            ocr_service=_FakeOcrService(),
            card_classifier=CardClassifier(),
            qr_service=QrService(),
            llm_extraction_service=_FakeLlmExtractionService(),
            reconciliation_service=ReconciliationService(),
            card_repository=CardRepository(db_session),
            image_storage=LocalImageStorage(str(tmp_path)),
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_card_processing_service] = override_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _read_fixture(name: str) -> bytes:
    return (_FIXTURES_DIR / name).read_bytes()


def test_full_lifecycle_upload_review_and_confirm(client):
    upload_response = client.post(
        "/cards", files={"file": ("card_with_qr.png", _read_fixture("card_with_qr.png"), "image/png")}
    )
    assert upload_response.status_code == 201
    card = upload_response.json()

    # QR ("Acme Corporation") vs LLM ("Acme Corp") genuinely disagree -> real conflict.
    assert card["status"] == "needs_review"
    assert card["fields"]["company"]["status"] == "conflict"
    assert card["fields"]["company"]["ocr_llm_value"] == "Acme Corp"
    assert card["fields"]["company"]["qr_value"] == "Acme Corporation"
    # Name matches on both sources -> confirmed automatically.
    assert card["fields"]["name"]["status"] == "confirmed"
    assert card["fields"]["name"]["value"] == "Jane Doe"
    assert card["qr"] == {"detected": True, "decoded": True}

    get_response = client.get(f"/cards/{card['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "needs_review"

    review_response = client.patch(
        f"/cards/{card['id']}/review", json={"company": "Acme Corporation"}
    )
    assert review_response.status_code == 200
    resolved = review_response.json()
    assert resolved["status"] == "confirmed"
    assert resolved["fields"]["company"]["value"] == "Acme Corporation"
    assert resolved["fields"]["company"]["status"] == "confirmed"

    final = client.get(f"/cards/{card['id']}").json()
    assert final["status"] == "confirmed"
    assert final["fields"]["company"]["value"] == "Acme Corporation"


def test_full_lifecycle_upload_without_qr_confirms_automatically(client):
    response = client.post(
        "/cards", files={"file": ("card_no_qr.png", _read_fixture("card_no_qr.png"), "image/png")}
    )

    assert response.status_code == 201
    card = response.json()
    assert card["status"] == "confirmed"
    assert card["fields"]["name"]["status"] == "unverified"
    assert card["qr"] == {"detected": False, "decoded": False}


def test_upload_non_card_image_returns_422_and_persists_nothing(client):
    response = client.post(
        "/cards", files={"file": ("non_card.png", _read_fixture("non_card.png"), "image/png")}
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "not_a_business_card"

    list_response = client.get("/cards")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0
