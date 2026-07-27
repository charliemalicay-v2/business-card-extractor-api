import cv2
import numpy as np
import pytest

from app.db.card_repository import CardRepository
from app.schemas import ExtractedField, LlmExtractionResult
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.exceptions import (
    ExtractionServiceUnavailableError,
    ImageStorageError,
    NotABusinessCardError,
)
from app.services.image_preprocessor import ImagePreprocessor
from app.services.image_storage.local_storage import LocalImageStorage
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService

_OCR_TEXT = "Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100"


class _FakeOcrService:
    def extract_text(self, image: np.ndarray) -> str:
        return _OCR_TEXT


class _FakeLlmExtractionService:
    def __init__(self, result: LlmExtractionResult | None = None, raises: Exception | None = None):
        self._result = result or self._default_result()
        self._raises = raises

    @staticmethod
    def _default_result() -> LlmExtractionResult:
        return LlmExtractionResult(
            name=ExtractedField(value="Jane Doe", confidence=0.95),
            position=ExtractedField(value="Sales Manager", confidence=0.9),
            company=ExtractedField(value="Acme Corp", confidence=0.9),
            email=ExtractedField(value="jane@acme.com", confidence=0.99),
            phone=ExtractedField(value="+1-555-0100", confidence=0.9),
        )

    def extract(self, ocr_text: str) -> LlmExtractionResult:
        if self._raises:
            raise self._raises
        return self._result


def _card_image_bytes() -> bytes:
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (345, 195), (0, 0, 0), 3)
    success, buffer = cv2.imencode(".png", image)
    assert success
    return buffer.tobytes()


def _card_image_with_qr_bytes() -> bytes:
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (345, 195), (0, 0, 0), 3)

    payload = "BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nORG:Acme Corp\nEND:VCARD"
    encoder = cv2.QRCodeEncoder.create()
    qr_matrix = encoder.encode(payload)
    qr_bgr = cv2.cvtColor(cv2.resize(qr_matrix, (120, 120), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
    image[40:160, 20:140] = qr_bgr

    success, buffer = cv2.imencode(".png", image)
    assert success
    return buffer.tobytes()


def _non_card_image_bytes() -> bytes:
    image = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(image, (200, 200), 15, (0, 0, 0), 2)
    success, buffer = cv2.imencode(".png", image)
    assert success
    return buffer.tobytes()


def _build_service(db_session, llm_service, image_storage) -> CardProcessingService:
    return CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=_FakeOcrService(),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=llm_service,
        reconciliation_service=ReconciliationService(),
        card_repository=CardRepository(db_session),
        image_storage=image_storage,
    )


def test_process_happy_path_without_qr_persists_confirmed_record(db_session, image_storage):
    service = _build_service(db_session, _FakeLlmExtractionService(), image_storage)

    record = service.process(_card_image_bytes(), image_filename="card.png")

    assert record.id is not None
    assert record.status == "confirmed"
    assert record.name_value == "Jane Doe"
    assert record.name_status == "unverified"
    assert record.qr_detected is False
    assert record.raw_ocr_text == _OCR_TEXT

    persisted = CardRepository(db_session).get_by_id(record.id)
    assert persisted is not None


def test_process_happy_path_with_qr_confirms_matching_fields(db_session, image_storage):
    service = _build_service(db_session, _FakeLlmExtractionService(), image_storage)

    record = service.process(_card_image_with_qr_bytes())

    assert record.qr_detected is True
    assert record.qr_decoded is True
    assert record.name_status == "confirmed"
    assert record.company_status == "confirmed"
    assert record.status == "confirmed"


def test_process_raises_and_persists_nothing_when_image_is_not_a_business_card(db_session, image_storage, tmp_path):
    service = _build_service(db_session, _FakeLlmExtractionService(), image_storage)

    with pytest.raises(NotABusinessCardError):
        service.process(_non_card_image_bytes())

    _, total = CardRepository(db_session).list()
    assert total == 0
    assert list(tmp_path.iterdir()) == []


def test_process_raises_and_persists_nothing_when_extraction_service_unavailable(db_session, image_storage, tmp_path):
    llm_service = _FakeLlmExtractionService(raises=ExtractionServiceUnavailableError("model down"))
    service = _build_service(db_session, llm_service, image_storage)

    with pytest.raises(ExtractionServiceUnavailableError):
        service.process(_card_image_bytes())

    _, total = CardRepository(db_session).list()
    assert total == 0
    assert list(tmp_path.iterdir()) == []


def test_process_persists_uploaded_image_and_sets_storage_key(db_session, image_storage, tmp_path):
    service = _build_service(db_session, _FakeLlmExtractionService(), image_storage)

    record = service.process(_card_image_bytes(), image_filename="card.png", content_type="image/png")

    assert record.image_storage_key is not None
    assert record.image_storage_key.endswith(".png")
    stored_path = tmp_path / record.image_storage_key
    assert stored_path.read_bytes() == _card_image_bytes()


def test_process_stores_image_with_no_extension_when_filename_and_content_type_are_absent(
    db_session, image_storage, tmp_path
):
    service = _build_service(db_session, _FakeLlmExtractionService(), image_storage)

    record = service.process(_card_image_bytes())

    assert record.image_storage_key is not None
    assert "." not in record.image_storage_key
    stored_path = tmp_path / record.image_storage_key
    assert stored_path.read_bytes() == _card_image_bytes()


def test_process_raises_and_persists_nothing_when_image_storage_fails(db_session, tmp_path):
    # Deliberately builds its own LocalImageStorage (rather than the shared `image_storage`
    # fixture) pointed at an unwritable directory, to force a storage failure.
    unwritable_dir = tmp_path / "unwritable"
    unwritable_dir.mkdir()
    unwritable_dir.chmod(0o400)
    service = _build_service(db_session, _FakeLlmExtractionService(), LocalImageStorage(str(unwritable_dir / "images")))

    with pytest.raises(ImageStorageError):
        service.process(_card_image_bytes(), image_filename="card.png")

    _, total = CardRepository(db_session).list()
    assert total == 0
