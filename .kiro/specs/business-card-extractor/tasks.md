# Implementation Plan: Business Card Extractor API

- [ ] 1. Project foundation
- [ ] 1.1 Set up project structure and tooling
  - Create FastAPI app skeleton (`app/main.py`), directory layout (`app/api`, `app/services`, `app/models`, `app/db`, `app/schemas`, `tests/`)
  - Add `pyproject.toml`/`requirements.txt` with fastapi, uvicorn, pytesseract, opencv-python, llama-cpp-python, sqlalchemy, psycopg, alembic, pydantic, pytest, pytest-asyncio
  - Configure `pytest` and a `.env`-based settings module (`app/config.py`) using `pydantic-settings` for DB URL, model path, size limits
  - _Requirements: NFR (Local Execution)_

- [ ] 1.2 Set up local PostgreSQL and migrations
  - Add `docker-compose.yml` (or setup doc) for local PostgreSQL
  - Configure SQLAlchemy engine/session (`app/db/session.py`) and Alembic migration environment
  - Create initial migration for the `business_cards` table per design's data model
  - _Requirements: 7.1_

- [ ] 2. Core data models and schemas
- [ ] 2.1 Define Pydantic schemas for pipeline data
  - Implement `ClassificationResult`, `QrResult`, `ExtractedField`, `LlmExtractionResult`, `ReconciledField`, `ReconciledCard`, `FieldStatus` enum in `app/schemas/`
  - Write unit tests validating enum constraints and required/optional field defaults
  - _Requirements: 4.1, 4.2, 5.2, 6.1_

- [ ] 2.2 Define `BusinessCardRecord` SQLAlchemy model
  - Implement ORM model mapping to the `business_cards` table (all `*_value`/`*_status`/`*_ocr_llm_value`/`*_qr_value` columns, `optional_fields` JSONB, `raw_ocr_text`, QR fields, timestamps)
  - Add DB-level CHECK constraints for `status` and `*_status` enums
  - Write a unit test creating/reading a record against a test DB session
  - _Requirements: 7.1, 7.2_

- [ ] 3. Image preprocessing and classification
- [ ] 3.1 Implement `ImagePreprocessor`
  - Implement `load()` (bytes → ndarray, raise `InvalidImageError` on decode failure) and `preprocess()` (grayscale, denoise, adaptive threshold, deskew)
  - Write unit tests with valid image fixtures and a corrupted-bytes fixture
  - _Requirements: 1.4, 3.1_

- [ ] 3.2 Implement `OcrService`
  - Implement `extract_text()` using pytesseract on a preprocessed image
  - Raise `OcrNoTextError` when result length is below a configurable minimum
  - Write unit tests with a fixture card image (expect non-empty text) and a blank image (expect `OcrNoTextError`)
  - _Requirements: 3.2, 3.3, 3.4_

- [ ] 3.3 Implement `CardClassifier`
  - Implement `check_shape()` (OpenCV contour/aspect-ratio/edge heuristic) and `check_text_patterns()` (regex for email-like/phone-like tokens in OCR text)
  - Implement `classify()` orchestrating shape check → OCR (via `OcrService`) → text pattern check, returning `ClassificationResult` with `failed_stage`/`reason_code`
  - Write unit tests covering: valid card, non-rectangular image (fails shape), rectangular-but-no-contact-info image (fails text pattern)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 4. QR code extraction
- [ ] 4.1 Implement `QrService.detect_and_decode`
  - Use `cv2.QRCodeDetector` to detect/decode QR payload from the image
  - Return `QrResult` with `detected`/`decoded`/`raw_payload`, handling no-QR and undecodable-QR cases distinctly
  - Write unit tests with a QR-containing fixture image, a no-QR fixture, and a corrupted/unreadable QR fixture
  - _Requirements: 5.1, 5.3, 5.4_

- [ ] 4.2 Implement `QrService.parse_payload`
  - Implement best-effort parsing for vCard and MECARD formats, plus a simple delimited-text fallback, mapping to `CardFields`
  - Write unit tests with sample vCard string, sample MECARD string, and an unparseable string (expect `None`)
  - _Requirements: 5.2_

- [ ] 5. LLM-based field extraction
- [ ] 5.1 Set up llama.cpp model loading and GBNF grammar
  - Implement model loader in `app/services/llm/model.py` using `llama-cpp-python`, loaded once at app startup (FastAPI lifespan event)
  - Author GBNF grammar constraining output to the `LlmExtractionResult` JSON schema (name, position, company, email, phone, optional_fields, confidence)
  - _Requirements: 4.1, NFR (Local Execution)_

- [ ] 5.2 Implement `LlmExtractionService.extract`
  - Build the structured-extraction prompt from OCR text, invoke the model with the grammar, parse JSON into `LlmExtractionResult`
  - Raise `ExtractionServiceUnavailableError` on model load/inference failure
  - Handle low-confidence/missing required fields by returning null values rather than raising (per Req 4.3)
  - Write unit tests mocking the llama.cpp binding for: full extraction, partial extraction (missing field), and unavailable-model error
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 6. Reconciliation logic
- [ ] 6.1 Implement `ReconciliationService.reconcile`
  - Implement per-field comparison (case-insensitive, whitespace-normalized) producing `ReconciledField` with `CONFIRMED`/`CONFLICT`/`UNVERIFIED` status
  - Compute `overall_status` (`needs_review` if any field is `CONFLICT`, else `confirmed`)
  - Write table-driven unit tests covering: match, mismatch, missing-QR-value, case/whitespace-only differences, all-optional-fields-passthrough
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_

- [ ] 7. Orchestration and persistence
- [ ] 7.1 Implement `CardRepository`
  - Implement `create()`, `get_by_id()`, `list()` (with status filter + pagination), `resolve_review()`
  - Write unit/integration tests against a test PostgreSQL database (create, fetch by id, list with filter, resolve updates status to `confirmed`)
  - _Requirements: 7.1, 7.2, 7.4, 8.1, 8.2, 6.6_

- [ ] 7.2 Implement `CardProcessingService.process`
  - Orchestrate: preprocess → classify (raise/stop on failure) → QR detect/decode/parse → LLM extract → reconcile → build `BusinessCardRecord` → persist via `CardRepository`
  - Ensure typed exceptions propagate unmodified for API-layer mapping; ensure no DB write occurs on classification/OCR/extraction failure
  - Write integration tests covering full pipeline happy path (with and without QR), classification-failure path (no DB row created), and extraction-unavailable path
  - _Requirements: 1.5, 2.6, 3.3, 4.5, 7.1, 7.2, 7.3_

- [ ] 8. API layer
- [ ] 8.1 Implement `POST /cards` endpoint
  - Implement multipart upload handling with content-type/size validation (Req 1.1–1.3) before invoking `CardProcessingService`
  - Wire a FastAPI exception handler mapping typed exceptions to the error-code table (400/413/422/503/500 responses)
  - Write integration tests for: successful upload (201 + expected body shape), oversized file (413), unsupported format (400), non-card image (422), extraction unavailable (503, mocked)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.6, 7.4_

- [ ] 8.2 Implement `GET /cards/{id}` and `GET /cards` endpoints
  - Implement single-record retrieval (404 on missing id) and list retrieval with `status` filter + pagination query params
  - Write integration tests for found/not-found single record and filtered/paginated list
  - _Requirements: 8.1, 8.2, 8.3_

- [ ] 8.3 Implement `PATCH /cards/{id}/review` endpoint
  - Accept resolved field values for a `needs_review` record, validate payload shape, call `CardRepository.resolve_review`, return updated record with `confirmed` status
  - Validate that a non-`needs_review` record or malformed payload returns `400 invalid_review_payload`
  - Write integration tests for successful resolution and invalid-payload rejection
  - _Requirements: 6.6_

- [ ] 9. End-to-end validation
- [ ] 9.1 Add end-to-end fixture tests
  - Assemble a small set of sample business card images (with QR, without QR, non-card image) as test fixtures
  - Write an e2e test: upload real sample → verify persisted fields → PATCH review resolution → verify final `confirmed` status
  - Write an e2e negative test: upload non-card image → verify `422` and no record created via `GET /cards`
  - _Requirements: 1–8 (full pipeline validation)_

- [ ] 9.2 Validate performance budget
  - Write a performance test measuring pipeline latency (excluding cold model load) for representative sample images against the 30s NFR budget
  - Document any bottleneck found (e.g., OCR preprocessing, LLM inference) as a follow-up note
  - _Requirements: NFR (Performance)_
