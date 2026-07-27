from app.db.card_repository import CardRepository
from app.models import BusinessCardRecord
from app.schemas import QrResult, ReconciledCard
from app.services.card_classifier import CardClassifier
from app.services.exceptions import NotABusinessCardError, OcrNoTextError
from app.services.image_preprocessor import ImagePreprocessor
from app.services.llm.extraction_service import LlmExtractionService
from app.services.ocr_service import OcrService
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService

_FIELD_NAMES = ("name", "position", "company", "email", "phone")


class CardProcessingService:
    def __init__(
        self,
        image_preprocessor: ImagePreprocessor,
        ocr_service: OcrService,
        card_classifier: CardClassifier,
        qr_service: QrService,
        llm_extraction_service: LlmExtractionService,
        reconciliation_service: ReconciliationService,
        card_repository: CardRepository,
    ):
        self._image_preprocessor = image_preprocessor
        self._ocr_service = ocr_service
        self._card_classifier = card_classifier
        self._qr_service = qr_service
        self._llm_extraction_service = llm_extraction_service
        self._reconciliation_service = reconciliation_service
        self._card_repository = card_repository

    def process(self, raw_bytes: bytes, image_filename: str | None = None) -> BusinessCardRecord:
        image = self._image_preprocessor.load(raw_bytes)

        classification = self._card_classifier.classify(image, self._ocr_service)
        if not classification.is_card:
            raise NotABusinessCardError(stage=classification.failed_stage or "unknown")

        ocr_text = classification.ocr_text
        if not ocr_text:
            raise OcrNoTextError("Classification succeeded but produced no OCR text.")

        qr_result = self._qr_service.detect_and_decode(image)
        llm_result = self._llm_extraction_service.extract(ocr_text)
        reconciled = self._reconciliation_service.reconcile(llm_result, qr_result)

        record = self._build_record(reconciled, qr_result, ocr_text, image_filename)
        return self._card_repository.create(record)

    def _build_record(
        self,
        reconciled: ReconciledCard,
        qr_result: QrResult,
        raw_ocr_text: str,
        image_filename: str | None,
    ) -> BusinessCardRecord:
        field_kwargs = {}
        for field_name in _FIELD_NAMES:
            reconciled_field = getattr(reconciled, field_name)
            field_kwargs[f"{field_name}_value"] = reconciled_field.value
            field_kwargs[f"{field_name}_status"] = reconciled_field.status.value
            field_kwargs[f"{field_name}_ocr_llm_value"] = reconciled_field.ocr_llm_value
            field_kwargs[f"{field_name}_qr_value"] = reconciled_field.qr_value

        return BusinessCardRecord(
            status=reconciled.overall_status,
            optional_fields=reconciled.optional_fields,
            raw_ocr_text=raw_ocr_text,
            qr_detected=qr_result.detected,
            qr_decoded=qr_result.decoded,
            qr_raw_payload=qr_result.raw_payload,
            image_filename=image_filename,
            **field_kwargs,
        )
