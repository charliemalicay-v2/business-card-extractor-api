import json
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_card_processing_service, get_card_repository, get_image_storage
from app.db.card_repository import CardRepository
from app.db.session import get_db
from app.main import app
from app.schemas import ExtractedField, LlmExtractionResult
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.exceptions import ExtractionServiceUnavailableError, ImageStorageError
from app.services.image_preprocessor import ImagePreprocessor
from app.services.image_storage.local_storage import LocalImageStorage
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


def _replacement_card_image_bytes() -> bytes:
    image = np.full((220, 360, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (350, 210), (0, 0, 0), 4)
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
    app.dependency_overrides[get_image_storage] = lambda: image_storage

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

    detail_response = client.get(f"/cards/{card_id}")
    assert "raw_ocr_text" in detail_response.json()


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


def test_get_card_returns_502_when_image_storage_url_fails(client, monkeypatch):
    import app.config as config_module

    class _FailingStorage:
        def url(self, key: str) -> str:
            raise ImageStorageError("presigned URL generation failed")

    # Upload while still on the local backend, so the create response's own image_url build
    # succeeds; only then switch to a non-local backend with a failing url() for the GET below.
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    monkeypatch.setattr(config_module.settings, "image_storage_backend", "s3")
    app.dependency_overrides[get_image_storage] = lambda: _FailingStorage()

    response = client.get(f"/cards/{card_id}")

    assert response.status_code == 502
    assert response.json()["error_code"] == "image_storage_unavailable"


def test_upload_card_returns_502_when_image_storage_put_fails(client, tmp_path):
    unwritable_dir = tmp_path / "unwritable"
    unwritable_dir.mkdir()
    unwritable_dir.chmod(0o400)

    app.dependency_overrides[get_card_processing_service] = lambda: CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=_FakeOcrService(),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=_FakeLlmExtractionService(),
        reconciliation_service=ReconciliationService(),
        card_repository=CardRepository(client.db_session),
        image_storage=LocalImageStorage(str(unwritable_dir / "images")),
    )

    response = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})

    assert response.status_code == 502
    assert response.json()["error_code"] == "image_storage_unavailable"

    _, total = CardRepository(client.db_session).list()
    assert total == 0


def test_get_card_image_returns_stored_bytes_with_content_type(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.get(f"/cards/{card_id}/image")

    assert response.status_code == 200
    assert response.content == _card_image_bytes()
    assert response.headers["content-type"] == "image/png"


def test_get_card_image_returns_404_for_unknown_record(client):
    response = client.get(f"/cards/{uuid.uuid4()}/image")

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_get_card_image_returns_404_when_record_has_no_stored_image(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    record = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id))
    record.image_storage_key = None
    client.db_session.commit()

    response = client.get(f"/cards/{card_id}/image")

    assert response.status_code == 404
    assert response.json()["error_code"] == "image_not_found"


def test_get_card_image_returns_404_when_file_missing_from_disk(client, tmp_path):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]
    key = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id)).image_storage_key
    (tmp_path / key).unlink()

    response = client.get(f"/cards/{card_id}/image")

    assert response.status_code == 404
    assert response.json()["error_code"] == "image_not_found"


def test_get_card_image_returns_404_for_non_local_backend(client, monkeypatch):
    import app.config as config_module

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    monkeypatch.setattr(config_module.settings, "image_storage_backend", "s3")

    response = client.get(f"/cards/{card_id}/image")

    assert response.status_code == 404
    assert response.json()["error_code"] == "image_not_found"


def test_update_card_updates_field_values(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(f"/cards/{card_id}", data={"company_value": "Updated Corp"})

    assert response.status_code == 200
    body = response.json()
    assert body["fields"]["company"]["value"] == "Updated Corp"

    persisted = client.get(f"/cards/{card_id}").json()
    assert persisted["fields"]["company"]["value"] == "Updated Corp"


def test_update_card_updates_optional_fields_from_json_string(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(
        f"/cards/{card_id}", data={"optional_fields": json.dumps({"fax": "+1-555-9999"})}
    )

    assert response.status_code == 200
    assert response.json()["optional_fields"] == {"fax": "+1-555-9999"}


def test_update_card_replaces_image_and_deletes_old_file(client, tmp_path):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]
    old_key = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id)).image_storage_key
    assert (tmp_path / old_key).exists()

    response = client.patch(
        f"/cards/{card_id}",
        files={"file": ("new_card.png", _replacement_card_image_bytes(), "image/png")},
    )

    assert response.status_code == 200
    new_key = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id)).image_storage_key
    assert new_key != old_key
    assert not (tmp_path / old_key).exists()
    assert (tmp_path / new_key).read_bytes() == _replacement_card_image_bytes()

    image_response = client.get(f"/cards/{card_id}/image")
    assert image_response.content == _replacement_card_image_bytes()


def test_update_card_returns_404_for_unknown_id(client):
    response = client.patch(f"/cards/{uuid.uuid4()}", data={"company_value": "Someone"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_update_card_rejects_empty_payload(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(f"/cards/{card_id}")

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_update_payload"


def test_update_card_rejects_invalid_optional_fields_json(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(f"/cards/{card_id}", data={"optional_fields": "not-json"})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_update_payload"


def test_update_card_rejects_non_object_optional_fields_json(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(f"/cards/{card_id}", data={"optional_fields": json.dumps(["not", "a", "dict"])})

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_update_payload"


def test_update_card_rejects_unsupported_replacement_image_content_type(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    response = client.patch(f"/cards/{card_id}", files={"file": ("card.txt", b"not an image", "text/plain")})

    assert response.status_code == 400
    assert response.json()["error_code"] == "unsupported_format"


def test_update_card_review_endpoint_still_works_independently(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    record = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id))
    record.status = "needs_review"
    record.company_status = "conflict"
    client.db_session.commit()

    update_response = client.patch(f"/cards/{card_id}", data={"phone_value": "+1-555-0200"})
    assert update_response.status_code == 200
    assert update_response.json()["fields"]["phone"]["value"] == "+1-555-0200"
    # Field update alone doesn't touch review state.
    assert update_response.json()["status"] == "needs_review"

    review_response = client.patch(f"/cards/{card_id}/review", json={"company": "Acme Corporation"})
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "confirmed"
    assert review_response.json()["fields"]["company"]["value"] == "Acme Corporation"
    # Review resolution didn't clobber the earlier field update.
    assert review_response.json()["fields"]["phone"]["value"] == "+1-555-0200"


def test_delete_card_returns_204_and_removes_record_and_image(client, tmp_path):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]
    key = CardRepository(client.db_session).get_by_id(uuid.UUID(card_id)).image_storage_key
    assert (tmp_path / key).exists()

    response = client.delete(f"/cards/{card_id}")

    assert response.status_code == 204
    assert not response.content
    assert not (tmp_path / key).exists()

    get_response = client.get(f"/cards/{card_id}")
    assert get_response.status_code == 404
    assert get_response.json()["error_code"] == "record_not_found"


def test_delete_card_returns_404_for_unknown_id(client):
    response = client.delete(f"/cards/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_delete_card_returns_404_for_already_deleted_id(client):
    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    first = client.delete(f"/cards/{card_id}")
    assert first.status_code == 204

    second = client.delete(f"/cards/{card_id}")
    assert second.status_code == 404
    assert second.json()["error_code"] == "record_not_found"


def test_delete_card_succeeds_even_when_image_storage_delete_fails(client):
    class _FailingDeleteStorage:
        def delete(self, key: str) -> None:
            raise ImageStorageError("simulated storage delete failure")

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    app.dependency_overrides[get_image_storage] = lambda: _FailingDeleteStorage()

    response = client.delete(f"/cards/{card_id}")

    assert response.status_code == 204

    _, total = CardRepository(client.db_session).list()
    assert total == 0


def test_update_card_returns_404_when_record_disappears_before_update(client):
    """Simulates a concurrent delete landing between the route's existence check and the
    actual repository.update() call, by wrapping the real repository so update() reports
    not-found even though get_by_id() still succeeds."""

    class _RaceyRepository:
        def __init__(self, real: CardRepository):
            self._real = real

        def get_by_id(self, record_id):
            return self._real.get_by_id(record_id)

        def update(self, record_id, fields):
            return None

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    real_repository = CardRepository(client.db_session)
    app.dependency_overrides[get_card_repository] = lambda: _RaceyRepository(real_repository)

    response = client.patch(f"/cards/{card_id}", data={"company_value": "Doesn't matter"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"


def test_delete_card_returns_404_when_record_disappears_before_delete(client):
    """Simulates a concurrent delete landing between the route's existence check and the
    actual repository.delete() call, by wrapping the real repository so delete() reports
    not-found even though get_by_id() still succeeds."""

    class _RaceyRepository:
        def __init__(self, real: CardRepository):
            self._real = real

        def get_by_id(self, record_id):
            return self._real.get_by_id(record_id)

        def delete(self, record_id):
            return False

    upload = client.post("/cards", files={"file": ("card.png", _card_image_bytes(), "image/png")})
    card_id = upload.json()["id"]

    real_repository = CardRepository(client.db_session)
    app.dependency_overrides[get_card_repository] = lambda: _RaceyRepository(real_repository)

    response = client.delete(f"/cards/{card_id}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "record_not_found"
