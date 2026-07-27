# Implementation Plan: Business Card Extractor API

- [x] 1. Project foundation
- [x] 1.1 Set up project structure and tooling
  - Create FastAPI app skeleton (`app/main.py`), directory layout (`app/api`, `app/services`, `app/models`, `app/db`, `app/schemas`, `tests/`)
  - Add `pyproject.toml`/`requirements.txt` with fastapi, uvicorn, pytesseract, opencv-python, llama-cpp-python, sqlalchemy, psycopg, alembic, pydantic, pytest, pytest-asyncio
  - Configure `pytest` and a `.env`-based settings module (`app/config.py`) using `pydantic-settings` for DB URL, model path, size limits
  - _Requirements: NFR (Local Execution)_
  - _Status: Done — `/health` endpoint verified passing via `pytest` in a real venv._

- [x] 1.2 Set up local PostgreSQL and migrations
  - Add `docker-compose.yml` (or setup doc) for local PostgreSQL
  - Configure SQLAlchemy engine/session (`app/db/session.py`) and Alembic migration environment
  - Create initial migration for the `business_cards` table per design's data model
  - _Requirements: 7.1_
  - _Status: Done — migration `0001_create_business_cards_table.py` compiled/syntax-checked; not yet run against a live Postgres instance (no DB running in this pass). Run `alembic upgrade head` once `docker-compose up -d` is available._

- [x] 2. Core data models and schemas
- [x] 2.1 Define Pydantic schemas for pipeline data
  - Implement `ClassificationResult`, `QrResult`, `ExtractedField`, `LlmExtractionResult`, `ReconciledField`, `ReconciledCard`, `FieldStatus` enum in `app/schemas/`
  - Write unit tests validating enum constraints and required/optional field defaults
  - _Requirements: 4.1, 4.2, 5.2, 6.1_
  - _Status: Done — `app/schemas/card.py` + `tests/test_schemas.py` (6 tests), all passing._

- [x] 2.2 Define `BusinessCardRecord` SQLAlchemy model
  - Implement ORM model mapping to the `business_cards` table (all `*_value`/`*_status`/`*_ocr_llm_value`/`*_qr_value` columns, `optional_fields` JSONB, `raw_ocr_text`, QR fields, timestamps)
  - Add DB-level CHECK constraints for `status` and `*_status` enums
  - Write a unit test creating/reading a record against a test DB session
  - _Requirements: 7.1, 7.2_
  - _Status: Done — `app/models/business_card.py`. Column set verified 1:1 against migration `0001` (30 columns) and CHECK constraint SQL text verified. Deviation from task wording: no live Postgres instance was available in this environment, so `tests/test_business_card_model.py` verifies table/column/constraint metadata directly instead of a live create/read round-trip. Run an integration test against `docker-compose up -d` postgres before considering this fully closed._

- [x] 3. Image preprocessing and classification
- [x] 3.1 Implement `ImagePreprocessor`
  - Implement `load()` (bytes → ndarray, raise `InvalidImageError` on decode failure) and `preprocess()` (grayscale, denoise, adaptive threshold, deskew)
  - Write unit tests with valid image fixtures and a corrupted-bytes fixture
  - _Requirements: 1.4, 3.1_
  - _Status: Done — `app/services/image_preprocessor.py` + `tests/test_image_preprocessor.py` (4 tests: valid decode, empty bytes, corrupted bytes, preprocess output shape), all passing._

- [x] 3.2 Implement `OcrService`
  - Implement `extract_text()` using pytesseract on a preprocessed image
  - Raise `OcrNoTextError` when result length is below a configurable minimum
  - Write unit tests with a fixture card image (expect non-empty text) and a blank image (expect `OcrNoTextError`)
  - _Requirements: 3.2, 3.3, 3.4_
  - _Status: Done — `app/services/ocr_service.py` + `tests/test_ocr_service.py` (2 tests). No Tesseract binary is installed in this environment, so `pytesseract.image_to_string` is monkeypatched rather than exercising the real OCR engine — install Tesseract locally and re-run against a real card image before trusting end-to-end OCR quality._

- [x] 3.3 Implement `CardClassifier`
  - Implement `check_shape()` (OpenCV contour/aspect-ratio/edge heuristic) and `check_text_patterns()` (regex for email-like/phone-like tokens in OCR text)
  - Implement `classify()` orchestrating shape check → OCR (via `OcrService`) → text pattern check, returning `ClassificationResult` with `failed_stage`/`reason_code`
  - Write unit tests covering: valid card, non-rectangular image (fails shape), rectangular-but-no-contact-info image (fails text pattern)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Status: Done — `app/services/card_classifier.py` + `tests/test_card_classifier.py` (9 tests), using a stub `OcrService` to isolate classifier logic from real OCR. Shape thresholds (area ratio ≥0.2, aspect ratio 1.3–2.4) are untuned heuristics — validate/tune against real card photos in task 9 (e2e fixtures)._

- [x] 4. QR code extraction
- [x] 4.1 Implement `QrService.detect_and_decode`
  - Use `cv2.QRCodeDetector` to detect/decode QR payload from the image
  - Return `QrResult` with `detected`/`decoded`/`raw_payload`, handling no-QR and undecodable-QR cases distinctly
  - Write unit tests with a QR-containing fixture image, a no-QR fixture, and a corrupted/unreadable QR fixture
  - _Requirements: 5.1, 5.3, 5.4_
  - _Status: Done — `app/services/qr_service.py`. Fixtures use a real QR code generated via `cv2.QRCodeEncoder` (available in the installed OpenCV 5.0) rather than a mocked detector, so the detect/decode round-trip is genuinely exercised. The "corrupted QR" test inverts only the central data region (leaving corner finder patterns intact) to hit the `detected=True, decoded=False` branch specifically — an earlier attempt that corrupted a horizontal strip destroyed detection entirely and didn't test the intended branch, caught by inspecting actual output before finalizing the test._

- [x] 4.2 Implement `QrService.parse_payload`
  - Implement best-effort parsing for vCard and MECARD formats, plus a simple delimited-text fallback, mapping to `CardFields`
  - Write unit tests with sample vCard string, sample MECARD string, and an unparseable string (expect `None`)
  - _Requirements: 5.2_
  - _Status: Done — `tests/test_qr_service.py` (7 tests total across 4.1/4.2). Note: the delimited-text fallback is intentionally permissive (first non-email/phone line becomes `name`), so "unparseable" in practice means an empty/whitespace-only payload — genuinely garbled non-empty text will still produce a best-effort guess rather than `None`, consistent with the design's "best-effort" framing._

- [x] 5. LLM-based field extraction
- [x] 5.1 Set up llama.cpp model loading and GBNF grammar
  - Implement model loader in `app/services/llm/model.py` using `llama-cpp-python`, loaded once at app startup (FastAPI lifespan event)
  - Author GBNF grammar constraining output to the `LlmExtractionResult` JSON schema (name, position, company, email, phone, optional_fields, confidence)
  - _Requirements: 4.1, NFR (Local Execution)_
  - _Status: Done — `app/services/llm/model.py` (lazy-imports `llama_cpp` inside `LlamaCppModel.__init__` so the module has no hard import-time dependency on it), `app/services/llm/grammar.gbnf`, and a FastAPI `lifespan` hook in `app/main.py` that loads the model once at startup and degrades gracefully (logs a warning, app still serves requests) if loading fails. **Caveat**: `llama-cpp-python` only ships as a source distribution and needs a C++ toolchain/cmake to build, which isn't available in this sandbox, so it was never actually installed — `LlamaCppModel` construction was verified to correctly raise `ExtractionServiceUnavailableError` via the real `ImportError` path (not simulated), and the lifespan hook was verified end-to-end (real `TestClient` startup, confirmed log warning + app still responds to `/health`). The GBNF grammar itself has **not** been validated against a real llama.cpp binding/model — do that before relying on it in production._

- [x] 5.2 Implement `LlmExtractionService.extract`
  - Build the structured-extraction prompt from OCR text, invoke the model with the grammar, parse JSON into `LlmExtractionResult`
  - Raise `ExtractionServiceUnavailableError` on model load/inference failure
  - Handle low-confidence/missing required fields by returning null values rather than raising (per Req 4.3)
  - Write unit tests mocking the llama.cpp binding for: full extraction, partial extraction (missing field), and unavailable-model error
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Status: Done — `app/services/llm/extraction_service.py` + `tests/test_llm_extraction_service.py` (5 tests) using a fake `LlmModel` (matching the `Protocol` in `model.py`) rather than mocking `llama_cpp` internals directly, since the package isn't installed here. Confirmed `pydantic.ValidationError` (not a generic exception) is what `model_validate_json` raises on malformed JSON, so the `except ValidationError` clause is correctly targeted rather than guessed._

- [x] 6. Reconciliation logic
- [x] 6.1 Implement `ReconciliationService.reconcile`
  - Implement per-field comparison (case-insensitive, whitespace-normalized) producing `ReconciledField` with `CONFIRMED`/`CONFLICT`/`UNVERIFIED` status
  - Compute `overall_status` (`needs_review` if any field is `CONFLICT`, else `confirmed`)
  - Write table-driven unit tests covering: match, mismatch, missing-QR-value, case/whitespace-only differences, all-optional-fields-passthrough
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_
  - _Status: Done — `app/services/reconciliation_service.py` + `tests/test_reconciliation_service.py` (11 tests). Optional-fields merge policy (not fully specified by the design): starts from QR's `optional_fields` and overlays the LLM's, so LLM wins on key collisions — documented via test, not just assumed. Bug caught during self-review before finalizing: the initial implementation treated "OCR/LLM value missing but QR value present" as a `CONFLICT` (comparing `None` against the QR value) instead of falling back to the QR value as `UNVERIFIED`, which is the symmetric case to the already-required "QR missing" handling (Req 6.4). Fixed and covered with a dedicated regression test before marking this done._

- [x] 7. Orchestration and persistence
- [x] 7.1 Implement `CardRepository`
  - Implement `create()`, `get_by_id()`, `list()` (with status filter + pagination), `resolve_review()`
  - Write unit/integration tests against a test PostgreSQL database (create, fetch by id, list with filter, resolve updates status to `confirmed`)
  - _Requirements: 7.1, 7.2, 7.4, 8.1, 8.2, 6.6_
  - _Status: Done — `app/db/card_repository.py` + `tests/test_card_repository.py` (7 tests) run against a **real local Postgres** (Docker Desktop was started and `docker-compose up -d` brought up the `postgres:16-alpine` container from task 1.2, which had never actually been run before). This also closes out a gap flagged back in task 1.2/2.2: `alembic upgrade head` was run for real and the resulting table was inspected via `psql \d business_cards`, confirming it matches the ORM model and design exactly (columns, types, check constraints, index). `tests/conftest.py` adds a `db_session` fixture that truncates `business_cards` after each test for isolation._

- [x] 7.2 Implement `CardProcessingService.process`
  - Orchestrate: preprocess → classify (raise/stop on failure) → QR detect/decode/parse → LLM extract → reconcile → build `BusinessCardRecord` → persist via `CardRepository`
  - Ensure typed exceptions propagate unmodified for API-layer mapping; ensure no DB write occurs on classification/OCR/extraction failure
  - Write integration tests covering full pipeline happy path (with and without QR), classification-failure path (no DB row created), and extraction-unavailable path
  - _Requirements: 1.5, 2.6, 3.3, 4.5, 7.1, 7.2, 7.3_
  - _Status: Done — `app/services/card_processing_service.py` + `tests/test_card_processing_service.py` (4 tests), constructor-injected with real `ImagePreprocessor`/`CardClassifier`/`QrService`/`ReconciliationService`/`CardRepository` (against real Postgres) but fake `OcrService`/`LlmExtractionService` (Tesseract binary and llama-cpp-python are unavailable in this sandbox, per tasks 3.2/5.1). Added `NotABusinessCardError` to `app/services/exceptions.py` for the classification-failure path. Caught and fixed a real test-fixture bug during this task: the QR happy-path fixture image was initially 300×350px (aspect ratio ~1.17), which failed the classifier's own shape gate (needs 1.3–2.4) for a reason unrelated to QR logic — diagnosed by inspecting actual contour output rather than guessing, then fixed by matching the working fixture's 200×350 dimensions. All 4 scenarios (happy path with/without QR, classification failure, extraction-unavailable) verified to produce zero DB rows on failure paths by querying `CardRepository.list()` after the raised exception, not merely asserting the exception type._

- [x] 8. API layer
- [x] 8.1 Implement `POST /cards` endpoint
  - Implement multipart upload handling with content-type/size validation (Req 1.1–1.3) before invoking `CardProcessingService`
  - Wire a FastAPI exception handler mapping typed exceptions to the error-code table (400/413/422/503/500 responses)
  - Write integration tests for: successful upload (201 + expected body shape), oversized file (413), unsupported format (400), non-card image (422), extraction unavailable (503, mocked)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.6, 7.4_
  - _Status: Done — `app/api/cards.py`, `app/api/dependencies.py`, `app/api/exception_handlers.py`, `app/schemas/response.py`. Two real bugs caught and fixed while writing the integration tests (not left as TODOs): (1) `Depends(get_card_processing_service)` resolved eagerly before the endpoint body ran, calling `get_model()` unconditionally — meaning content-type/size validation would never be reached whenever the LLM wasn't loaded, always returning 503 first. Fixed with a `_LazyLlmModel` wrapper in `app/api/dependencies.py` that defers the `get_model()` call until inference is actually invoked inside `process()`, after validation and classification. (2) `HTTPException(detail={...})` responses were nested under `{"detail": {...}}` by FastAPI's default handling, not matching the flat `{error_code, message}` shape the typed-exception handlers and the design's `ErrorResponse` schema use — fixed with a generic `HTTPException` handler in `exception_handlers.py` that flattens dict `detail` to the top level. The 503 test deliberately uses the real (un-mocked) `LlmExtractionService`/`_LazyLlmModel`/`get_model()` chain — llama-cpp-python's absence in this sandbox is what genuinely produces the 503, not a simulated one. Also had to install `python-multipart` (already listed in `requirements.txt` from task 1.1 but not yet installed in the working venv) since FastAPI raises at import time without it once a `File(...)` param exists._

- [x] 8.2 Implement `GET /cards/{id}` and `GET /cards` endpoints
  - Implement single-record retrieval (404 on missing id) and list retrieval with `status` filter + pagination query params
  - Write integration tests for found/not-found single record and filtered/paginated list
  - _Requirements: 8.1, 8.2, 8.3_
  - _Status: Done — same files as 8.1. Query param is named `status` per the design's table (not `status_filter`), requiring the `fastapi.status` import to be aliased to `http_status` throughout `cards.py` to avoid shadowing._

- [x] 8.3 Implement `PATCH /cards/{id}/review` endpoint
  - Accept resolved field values for a `needs_review` record, validate payload shape, call `CardRepository.resolve_review`, return updated record with `confirmed` status
  - Validate that a non-`needs_review` record or malformed payload returns `400 invalid_review_payload`
  - Write integration tests for successful resolution and invalid-payload rejection
  - _Requirements: 6.6_
  - _Status: Done — 4 tests covering successful resolution (record manually forced into `needs_review`/`conflict` state, since the fake OCR/LLM pipeline never naturally disagrees with itself), rejection of a non-`needs_review` record, rejection of an empty payload, and 404 for an unknown id. All 13 API tests + full 76-test suite pass._

- [x] 9. End-to-end validation
- [x] 9.1 Add end-to-end fixture tests
  - Assemble a small set of sample business card images (with QR, without QR, non-card image) as test fixtures
  - Write an e2e test: upload real sample → verify persisted fields → PATCH review resolution → verify final `confirmed` status
  - Write an e2e negative test: upload non-card image → verify `422` and no record created via `GET /cards`
  - _Requirements: 1–8 (full pipeline validation)_
  - _Status: Done — real fixture PNG files committed at `tests/fixtures/{card_no_qr,card_with_qr,non_card}.png` (not inline byte strings), generated via a one-off script and independently verified to actually decode as expected (`QrService` against `card_with_qr.png` genuinely returns the embedded vCard) before being used in tests. `tests/test_e2e_card_lifecycle.py` (3 tests) drives the full HTTP stack (`TestClient` → routing → exception handlers → real Postgres) with fake OCR/LLM only. Made the QR-happy-path fixture encode `ORG:Acme Corporation` while the fake LLM returns `"Acme Corp"` **on purpose**, so the e2e test's `needs_review`/`conflict`/review-resolution flow is driven by real `ReconciliationService` logic detecting a genuine mismatch, rather than manually forcing DB state into `needs_review` the way the task 8.3 unit test had to (documented there as a known simplification) — this is a strictly stronger test of the review workflow._

- [x] 9.2 Validate performance budget
  - Write a performance test measuring pipeline latency (excluding cold model load) for representative sample images against the 30s NFR budget
  - Document any bottleneck found (e.g., OCR preprocessing, LLM inference) as a follow-up note
  - _Status: Done — `tests/test_performance.py`. Measured non-OCR/non-LLM pipeline overhead (image decode/preprocess, shape classification, real QR decode, reconciliation, real Postgres write) at 5 fixture runs: 23–87ms, comfortably within the 30s budget. **Explicit caveat, not a clean pass**: this cannot measure the two stages the design document itself identifies as the actual cost drivers — real Tesseract OCR and real llama.cpp inference — because neither is installed in this sandbox (tasks 3.2, 5.1). The measured number is a lower bound, not a real end-to-end latency figure; re-run with real OCR/LLM wired in before trusting the 30s budget in production._
  - _Requirements: NFR (Performance)_
