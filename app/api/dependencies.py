from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.card_repository import CardRepository
from app.db.session import get_db
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.image_preprocessor import ImagePreprocessor
from app.services.llm.extraction_service import LlmExtractionService
from app.services.llm.model import get_model
from app.services.ocr_service import OcrService
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService


def get_card_repository(db: Session = Depends(get_db)) -> CardRepository:
    return CardRepository(db)


class _LazyLlmModel:
    """Defers fetching the loaded model until inference is actually requested, so upload
    validation (content type, size) isn't blocked by LLM availability at dependency-resolution
    time -- see Req 1.1-1.3 vs Req 4.5 ordering."""

    def generate_json(self, prompt: str) -> str:
        return get_model().generate_json(prompt)


def get_card_processing_service(
    repository: CardRepository = Depends(get_card_repository),
) -> CardProcessingService:
    return CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=OcrService(),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=LlmExtractionService(_LazyLlmModel()),
        reconciliation_service=ReconciliationService(),
        card_repository=repository,
    )
