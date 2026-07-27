"""Performance check against the 30s pipeline-latency NFR (design.md, Non-Functional
Requirements: Performance).

IMPORTANT CAVEAT: real Tesseract OCR and real llama.cpp inference are not available in
this sandbox (see tasks 3.2 and 5.1), so this measures everything *except* those two
stages: image decode/preprocess, OpenCV shape classification, real QR detect/decode,
reconciliation, and a real Postgres write. In production, OCR (typically hundreds of ms
to a few seconds for Tesseract on a small image) and LLM inference (the dominant cost --
likely several seconds per call for a local CPU-bound llama.cpp model, more on first
call if the model is cold) are the actual bottlenecks this test cannot see. This test
should be re-run with real OCR/LLM wired in once both are available, to get a true
end-to-end number against the 30s budget.
"""

import time
from pathlib import Path

from app.db.card_repository import CardRepository
from app.schemas import ExtractedField, LlmExtractionResult
from app.services.card_classifier import CardClassifier
from app.services.card_processing_service import CardProcessingService
from app.services.image_preprocessor import ImagePreprocessor
from app.services.image_storage.local_storage import LocalImageStorage
from app.services.qr_service import QrService
from app.services.reconciliation_service import ReconciliationService

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_NFR_BUDGET_SECONDS = 30


class _FakeOcrService:
    def extract_text(self, image) -> str:
        return "Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100"


class _FakeLlmExtractionService:
    def extract(self, ocr_text: str) -> LlmExtractionResult:
        return LlmExtractionResult(
            name=ExtractedField(value="Jane Doe", confidence=0.95),
            position=ExtractedField(value="Sales Manager", confidence=0.9),
            company=ExtractedField(value="Acme Corp", confidence=0.9),
            email=ExtractedField(value="jane@acme.com", confidence=0.99),
            phone=ExtractedField(value="+1-555-0100", confidence=0.9),
        )


def test_pipeline_latency_excluding_ocr_and_llm_stays_well_within_nfr_budget(db_session, tmp_path):
    service = CardProcessingService(
        image_preprocessor=ImagePreprocessor(),
        ocr_service=_FakeOcrService(),
        card_classifier=CardClassifier(),
        qr_service=QrService(),
        llm_extraction_service=_FakeLlmExtractionService(),
        reconciliation_service=ReconciliationService(),
        card_repository=CardRepository(db_session),
        image_storage=LocalImageStorage(str(tmp_path)),
    )
    raw_bytes = (_FIXTURES_DIR / "card_with_qr.png").read_bytes()

    durations = []
    for _ in range(5):
        start = time.perf_counter()
        service.process(raw_bytes, image_filename="card_with_qr.png")
        durations.append(time.perf_counter() - start)

    max_duration = max(durations)
    print(f"\nNon-OCR/LLM pipeline latency over 5 runs: {durations} (max={max_duration:.4f}s)")

    assert max_duration < _NFR_BUDGET_SECONDS
