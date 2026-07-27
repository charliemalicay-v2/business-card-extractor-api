import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_card_processing_service, get_image_storage
from app.db.card_repository import CardRepository
from app.db.session import get_db
from app.main import app
from app.schemas import ExtractedField, LlmExtractionResult
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.exceptions import ExtractionServiceUnavailableError
from app.services.image_preprocessor import ImagePreprocessor
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService

_OCR_TEXT = "Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100"
_NON_CARD_OCR_TEXT = "Just some random words on a page"


class _FakeOcrService:
    def __init__(self, text: str = _OCR_TEXT):
        self._text = text

    def extract_text(self, image: np.ndarray) -> str:
        return self._text


class _FakeLlmExtractionService:
    def extract(self, ocr_text: str) -> LlmExtractionResult:
        return LlmExtractionResult(
            name=ExtractedField(value="Jane Doe", confidence=0.95),
            position=ExtractedField(value="Sales Manager", confidence=0.9),
            company=ExtractedField(value="Acme Corp", confidence=0.9),
            email=ExtractedField(value="jane@acme.com", confidence=0.99),
            phone=ExtractedField(value="+1-555-0100", confidence=0.9),
        )


def _card_image_bytes() -> bytes:
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (345, 195), (0, 0, 0), 3)
    success, buffer = cv2.imencode(".png", image)
    assert success
    return buffer.tobytes()


@pytest.fixture
def client(db_session, image_storage):
    def override_get_db():
        yield db_session

    def override_full_fake_service():
        return CardProcessingService(
            image_preprocessor=ImagePreprocessor(),
            ocr_service=_FakeOcrService(),
            card_classifier=CardClassifier(),
            qr_service=QrService(),
            llm_extraction_service=_FakeLlmExtractionService(),
            reconciliation_service=ReconciliationService(),
            card_repository=CardRepository(db_session),
            image_storage=image_storage,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_card_processing_service] = override_full_fake_service

    with TestClient(app) as test_client:
        test_client.db_session = db_session
        yield test_client

    app.dependency_overrides.clear()


def test_upload_card_success_returns_201_with_expected_shape(client):
    response = client.post(
        "/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["fields"]["name"]["value"] == "Jane Doe"
    assert body["fields"]["email"]["value"] == "jane@acme.com"
    assert body["qr"] == {"detected": False, "decoded": False}
    assert "id" in body


def test_upload_card_rejects_unsupported_content_type(client):
    response = client.post(
        "/cards", files={"file": ("card.txt", b"not an image", "text/plain")}
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "unsupported_format"


def test_upload_card_rejects_oversized_file(client, monkeypatch):
    import app.config as config_module

    monkeypatch.setattr(config_module.settings, "max_upload_size_bytes", 10)

    response = client.post(
        "/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")}
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "file_too_large"


def test_upload_card_rejects_empty_file(client):
    response = client.post("/cards", files={"file": ("card.png", b"", "image/png")})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_image"


def test_upload_card_returns_422_for_non_card_image(client, image_storage):
    app.dependency_overrides[get_card_processing_service] = lambda: CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=_FakeOcrService(text=_NON_CARD_OCR_TEXT),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=_FakeLlmExtractionService(),
        reconciliation_service=ReconciliationService(),
        card_repository=CardRepository(client.db_session),
        image_storage=image_storage,
    )

    response = client.post(
        "/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "not_a_business_card"
    assert body["stage"] == "text_pattern"


def test_upload_card_returns_503_when_llm_extraction_service_unavailable(client, image_storage):
    """Forces unavailability via a fake model that raises, rather than relying on
    llama-cpp-python being absent from the environment (which made this test
    environment-fragile -- it silently returned 201 once llama-cpp-python was actually
    installed and a real GGUF model was available, per manual real-model verification)."""

    class _UnavailableModel:
        def generate_json(self, prompt: str) -> str:
            raise ExtractionServiceUnavailableError("model deliberately unavailable for this test")

    def override_ocr_only_fake_service():
        from app.services.llm.extraction_service import LlmExtractionService

        return CardProcessingService(
            image_preprocessor=ImagePreprocessor(),
            ocr_service=_FakeOcrService(),
            card_classifier=CardClassifier(),
            qr_service=QrService(),
            llm_extraction_service=LlmExtractionService(_UnavailableModel()),
            reconciliation_service=ReconciliationService(),
            card_repository=CardRepository(client.db_session),
            image_storage=image_storage,
        )

    app.dependency_overrides[get_card_processing_service] = override_ocr_only_fake_service

    response = client.post(
        "/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")}
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "extraction_service_unavailable"


def test_get_card_returns_persisted_record(client):
    upload_response = client.post(
        "/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")}
    )
    card_id = upload_response.json()["id"]

    response = client.get(f"/cards/{card_id}")

    assert response.status_code == 200
    assert response.json()["id"] == card_id


def test_get_card_returns_404_for_unknown_id(client):
    response = client.get(f"/cards/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_resolve_review_updates_conflicting_field_and_confirms_record(client, image_storage):
    app.dependency_overrides[get_card_processing_service] = lambda: CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=_FakeOcrService(),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=_FakeLlmExtractionService(),
        reconciliation_service=ReconciliationService(),
        card_repository=CardRepository(client.db_session),
        image_storage=image_storage,
    )

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    # Manually force the record into needs_review with a company conflict, bypassing the
    # pipeline (which has no real QR/LLM to disagree in this test) to exercise the resolution
    # endpoint's own logic directly.
    record = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id))
    record.status = "needs_review"
    record.company_status = "conflict"
    client.db_session.commit()

    response = client.patch(f"/cards/{card_id}/review", json={"company": "Acme Corporation"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["fields"]["company"]["value"] == "Acme Corporation"
    assert body["fields"]["company"]["status"] == "confirmed"


def test_resolve_review_rejects_record_not_pending_review(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]  # already "confirmed" from the happy path

    response = client.patch(f"/cards/{card_id}/review", json={"name": "Someone Else"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_review_payload"


def test_resolve_review_rejects_empty_payload(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]
    record = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id))
    record.status = "needs_review"
    client.db_session.commit()

    response = client.patch(f"/cards/{card_id}/review", json={})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_review_payload"


def test_resolve_review_returns_404_for_unknown_id(client):
    response = client.patch(f"/cards/{uuid.uuid4()}/review", json={"name": "Someone"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_list_cards_filters_by_status_and_paginates(client):
    for _ in range(3):
        client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})

    response = client.get("/cards", params={"status": "confirmed", "page": 1, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_list_cards_items_omit_raw_ocr_text_but_detail_view_includes_it(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    list_response = client.get("/cards")
    list_item = next(item for item in list_response.json()["items"] if item["id"] == card_id)
    assert "raw_ocr_text" not in list_item


def test_upload_card_response_includes_local_image_url(client):
    response = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})

    body = response.json()
    assert body["image_url"] == f"/cards/{body['id']}/image"


def test_get_card_response_includes_local_image_url(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.get(f"/cards/{card_id}")

    assert response.json()["image_url"] == f"/cards/{card_id}/image"


def test_list_cards_items_include_image_url(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    list_response = client.get("/cards")
    list_item = next(item for item in list_response.json()["items"] if item["id"] == card_id)

    assert list_item["image_url"] == f"/cards/{card_id}/image"


def test_get_card_image_url_is_null_when_record_has_no_stored_image(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    # Simulate a legacy record from before image storage existed (image_storage_key is NULL).
    record = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id))
    record.image_storage_key = None
    client.db_session.commit()

    response = client.get(f"/cards/{card_id}")

    assert response.json()["image_url"] is None


def test_get_card_image_url_uses_storage_backend_url_for_non_local_backend(client, monkeypatch):
    import app.config as config_module

    class _FakeNonLocalStorage:
        def url(self, key: str) -> str:
            return f"https://example-bucket.s3.amazonaws.com/{key}"

    monkeypatch.setattr(config_module.settings, "image_storage_backend", "s3")
    app.dependency_overrides[get_image_storage] = lambda: _FakeNonLocalStorage()

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]
    key = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id)).image_storage_key

    response = client.get(f"/cards/{card_id}")

    assert response.json()["image_url"] == f"https://example-bucket.s3.amazonaws.com/{key}"

    detail_response = client.get(f"/cards/{card_id}")
    assert "raw_ocr_text" in detail_response.json()
