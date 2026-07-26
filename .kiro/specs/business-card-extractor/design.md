# Design Document: Business Card Extractor API

## Overview
A FastAPI backend that accepts a business card image, validates it, extracts text via OpenCV + Tesseract, structures the text into contact fields via a locally-run llama.cpp model, cross-checks against any QR code payload, and persists the reconciled record to a local PostgreSQL database. All processing (OCR, CV, LLM) runs locally with no external network calls. No authentication (single-user/internal tool). Processing is synchronous per request (the 30s NFR budget supports a request/response flow without a job queue).

## Architecture

### System Overview
```
Client
  │  POST /cards (multipart image)
  ▼
FastAPI App
  ├─ UploadRouter        → validates request-level constraints (size, type)
  ├─ CardProcessingService (orchestrator, called synchronously)
  │    ├─ ImagePreprocessor (OpenCV)          — decode, shape check, deskew/denoise
  │    ├─ CardClassifier (OpenCV + OCR text)  — "is this a business card?"
  │    ├─ OcrService (Tesseract via pytesseract)
  │    ├─ QrService (OpenCV QRCodeDetector)
  │    ├─ LlmExtractionService (llama.cpp via llama-cpp-python)
  │    ├─ ReconciliationService              — merge OCR/LLM + QR, detect conflicts
  │    └─ CardRepository (SQLAlchemy → PostgreSQL)
  ▼
PostgreSQL (local)
```

### Data Flow (happy path)
1. Client uploads image → FastAPI validates content-type/size.
2. `ImagePreprocessor` decodes bytes to an OpenCV matrix, applies grayscale/deskew/denoise/contrast steps.
3. `CardClassifier` runs the OpenCV shape/edge heuristic; if it passes, runs Tesseract OCR and checks the raw text for email/phone-like patterns.
4. If classification fails at either stage → return `422` with reason code, no DB write.
5. If classification passes → `OcrService` returns cleaned OCR text (already computed during classification, reused).
6. `QrService` attempts QR detection/decode in parallel conceptually (executed sequentially in v1) → best-effort field parse.
7. `LlmExtractionService` sends OCR text to the local llama.cpp model with a structured-extraction prompt (JSON-mode/grammar-constrained output) → structured fields + confidence.
8. `ReconciliationService` compares LLM fields vs QR fields per-field → produces final field set + per-field status (`confirmed` / `conflict` / `unverified`) + overall record status (`confirmed` / `needs_review`).
9. `CardRepository` persists the record (required fields, optional fields, raw OCR text, QR raw payload, statuses).
10. API returns the persisted record.

### Technology Decisions

**FastAPI** — async-capable, native multipart upload support, automatic OpenAPI docs, Pydantic validation aligns with the structured-field requirement.

**Tesseract via `pytesseract`** — required by the spec; wraps the CLI, straightforward integration with OpenCV-preprocessed images.

**OpenCV (`opencv-python`)** — used both for image preprocessing (Requirement 3) and QR detection via `cv2.QRCodeDetector` (Requirement 5), avoiding an extra QR dependency.

**llama.cpp via `llama-cpp-python`** — runs a local GGUF model in-process (no separate server to manage), supports grammar-constrained/JSON output which is used to force the model to emit the required field schema reliably.

**SQLAlchemy + `psycopg` (or `asyncpg`) + local PostgreSQL** — per the decision to use local PostgreSQL only (no Supabase for this feature). SQLAlchemy gives migration support via Alembic and a clean repository boundary if cloud sync is added later.

**Synchronous processing, no queue** — the NFR budget (30s) and single-user/internal scope don't justify a background job/queue system for v1. Documented as a future extension point, not built now.

### Decision: Card Validation Strategy
**Context:** Requirement 2 mandates a combined OpenCV + OCR heuristic to reject non-business-card images before expensive LLM processing.

**Options Considered:**
1. **OpenCV only (shape/aspect ratio)** — Pros: fast, cheap. Cons: many non-card rectangular objects would false-positive (receipts, ID cards, photos of paper).
2. **OCR-only text pattern** — Pros: directly checks for contact-like content. Cons: expensive to run OCR on clearly non-card images (e.g., a landscape photo); wastes time before rejecting.
3. **Both combined, staged** — OpenCV first (cheap gate) → OCR text pattern check second (confirms content) → reject early if either fails.

**Decision:** Option 3 (staged combination), matching the user's explicit choice.

**Rationale:** Staging cheap checks before expensive ones minimizes wasted work on obviously-invalid images, while the OCR text-pattern stage catches non-cards that happen to be card-shaped (e.g., a plain rectangle photo).

**Implications:** `CardClassifier` must expose two internal steps (`check_shape()`, `check_text_patterns()`), each returning a reason code on failure so error responses are specific.

### Decision: LLM Output Reliability
**Context:** llama.cpp output must reliably map to the required field schema (Name, Position, Company, Email, Phone) plus optional fields, without hallucinating structure the app can't parse.

**Options Considered:**
1. **Free-form prompt + regex post-parse** — Pros: simple. Cons: fragile, brittle to model phrasing drift.
2. **Grammar-constrained JSON output (GBNF grammar via llama-cpp-python)** — Pros: guarantees valid JSON matching a schema; Cons: requires authoring/maintaining a GBNF grammar.

**Decision:** Grammar-constrained JSON output.

**Rationale:** Directly produces parseable, schema-conformant output, eliminating a fragile regex-parsing layer and reducing malformed-response failure modes.

**Implications:** `LlmExtractionService` owns the GBNF grammar definition (fields + types) and returns a typed Pydantic model, never raw text, to the reconciliation layer.

## Components and Interfaces

### `ImagePreprocessor`
**Purpose:** Convert uploaded bytes into an OpenCV image ready for classification/OCR.

**Responsibilities:**
- Decode bytes → `numpy.ndarray` (reject if decode fails → corrupted file error).
- Grayscale conversion, denoising, adaptive thresholding, deskew.

**Interface:**
```python
class ImagePreprocessor:
    def load(self, raw_bytes: bytes) -> np.ndarray: ...
    def preprocess(self, image: np.ndarray) -> np.ndarray: ...
```

### `CardClassifier`
**Purpose:** Determine whether the image is a business card (Requirement 2).

**Interface:**
```python
class ClassificationResult(BaseModel):
    is_card: bool
    failed_stage: Literal["shape", "text_pattern"] | None
    reason_code: str | None
    ocr_text: str | None  # populated if OCR ran, reused downstream

class CardClassifier:
    def check_shape(self, image: np.ndarray) -> bool: ...
    def check_text_patterns(self, ocr_text: str) -> bool: ...
    def classify(self, image: np.ndarray, ocr_service: "OcrService") -> ClassificationResult: ...
```

### `OcrService`
**Purpose:** Run Tesseract OCR on a preprocessed image (Requirement 3).

**Interface:**
```python
class OcrService:
    def extract_text(self, image: np.ndarray) -> str: ...
```
- Raises `OcrNoTextError` if result is empty/near-empty (< configurable min char threshold).

### `QrService`
**Purpose:** Detect, decode, and parse QR code data (Requirement 5).

**Interface:**
```python
class QrResult(BaseModel):
    detected: bool
    decoded: bool
    raw_payload: str | None
    parsed_fields: CardFields | None  # best-effort parse (vCard/MECARD/delimited)

class QrService:
    def detect_and_decode(self, image: np.ndarray) -> QrResult: ...
    def parse_payload(self, payload: str) -> CardFields | None: ...
```

### `LlmExtractionService`
**Purpose:** Structure OCR text into contact fields using a local llama.cpp model (Requirement 4).

**Interface:**
```python
class ExtractedField(BaseModel):
    value: str | None
    confidence: float  # 0.0–1.0, default 0.5 if model doesn't emit confidence

class LlmExtractionResult(BaseModel):
    name: ExtractedField
    position: ExtractedField
    company: ExtractedField
    email: ExtractedField
    phone: ExtractedField
    optional_fields: dict[str, str]  # e.g., address, website, fax

class LlmExtractionService:
    def extract(self, ocr_text: str) -> LlmExtractionResult: ...
```
- Raises `ExtractionServiceUnavailableError` if the model fails to load or errors, per Requirement 4.5.

### `ReconciliationService`
**Purpose:** Merge LLM and QR field values, detect conflicts, compute record status (Requirement 6).

**Interface:**
```python
class FieldStatus(str, Enum):
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    UNVERIFIED = "unverified"

class ReconciledField(BaseModel):
    value: str | None
    status: FieldStatus
    ocr_llm_value: str | None
    qr_value: str | None

class ReconciledCard(BaseModel):
    name: ReconciledField
    position: ReconciledField
    company: ReconciledField
    email: ReconciledField
    phone: ReconciledField
    optional_fields: dict[str, str]
    overall_status: Literal["confirmed", "needs_review"]

class ReconciliationService:
    def reconcile(self, llm_result: LlmExtractionResult, qr_result: QrResult) -> ReconciledCard: ...
```
- Comparison is case-insensitive and whitespace-normalized per Requirement 6.2.

### `CardProcessingService` (Orchestrator)
**Purpose:** Coordinate the full pipeline end-to-end for a single upload.

**Interface:**
```python
class CardProcessingService:
    def process(self, raw_bytes: bytes) -> BusinessCardRecord: ...
```
- Raises typed exceptions (`ValidationError`, `OcrNoTextError`, `ExtractionServiceUnavailableError`) that the API layer maps to HTTP status codes.

### `CardRepository`
**Purpose:** Persist and retrieve `BusinessCardRecord` rows (Requirements 7, 8).

**Interface:**
```python
class CardRepository:
    def create(self, record: BusinessCardRecord) -> BusinessCardRecord: ...
    def get_by_id(self, record_id: UUID) -> BusinessCardRecord | None: ...
    def list(self, status: str | None, page: int, page_size: int) -> tuple[list[BusinessCardRecord], int]: ...
    def resolve_review(self, record_id: UUID, resolved_fields: dict) -> BusinessCardRecord: ...
```

### API Endpoints

| Method | Path | Purpose | Requirement |
|--------|------|---------|-------------|
| POST | `/cards` | Upload image, run full pipeline, return persisted record | 1, 2, 3, 4, 5, 6, 7 |
| GET | `/cards/{id}` | Retrieve a single record | 8.1, 8.3 |
| GET | `/cards` | List records, filter by `status`, paginate | 8.2 |
| PATCH | `/cards/{id}/review` | Submit resolved field values for a `needs_review` record | 6.6 |

**POST /cards — response shape (201):**
```json
{
  "id": "b3f1...-uuid",
  "status": "needs_review",
  "fields": {
    "name": {"value": "Jane Doe", "status": "confirmed"},
    "position": {"value": "Sales Manager", "status": "unverified"},
    "company": {"value": "Acme Corp", "status": "conflict", "ocr_llm_value": "Acme Corp", "qr_value": "Acme Corporation"},
    "email": {"value": "jane@acme.com", "status": "confirmed"},
    "phone": {"value": "+1-555-0100", "status": "confirmed"}
  },
  "optional_fields": {"website": "acme.com"},
  "qr": {"detected": true, "decoded": true},
  "raw_ocr_text": "Jane Doe\nSales Manager\n...",
  "created_at": "2026-07-26T10:00:00Z"
}
```

**Error response shape (4xx/5xx):**
```json
{ "error_code": "not_a_business_card", "message": "Image does not appear to be a business card.", "stage": "shape" }
```

## Data Models

### `business_cards` table

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (PK) | Yes | Record identifier |
| status | varchar | Yes | `needs_review` \| `confirmed` |
| name_value | varchar | No | Final reconciled value |
| name_status | varchar | Yes | `confirmed` \| `conflict` \| `unverified` |
| name_ocr_llm_value | varchar | No | Raw LLM-extracted value |
| name_qr_value | varchar | No | Raw QR-parsed value |
| position_value / position_status / position_ocr_llm_value / position_qr_value | varchar | No/Yes/No/No | Same pattern as name |
| company_value / company_status / company_ocr_llm_value / company_qr_value | varchar | No/Yes/No/No | Same pattern as name |
| email_value / email_status / email_ocr_llm_value / email_qr_value | varchar | No/Yes/No/No | Same pattern as name |
| phone_value / phone_status / phone_ocr_llm_value / phone_qr_value | varchar | No/Yes/No/No | Same pattern as name |
| optional_fields | jsonb | No | Extra fields (address, website, fax, etc.) |
| raw_ocr_text | text | Yes | Full OCR output for traceability |
| qr_detected | boolean | Yes | Whether a QR code was found |
| qr_decoded | boolean | Yes | Whether the QR payload was successfully decoded |
| qr_raw_payload | text | No | Raw decoded QR string |
| image_filename | varchar | No | Original filename (metadata only; see Open Question on file retention) |
| created_at | timestamptz | Yes | Upload time |
| updated_at | timestamptz | Yes | Last modification (e.g., review resolution) |

**Validation Rules:**
- `status` and each `*_status` restricted to their enum values at the application layer (Pydantic) and via a CHECK constraint at the DB layer.
- `email_value`, when present, validated as a syntactically valid email before persistence (does not block save on invalid format — stored as-is with `unverified`/`conflict` status; format validation is a warning, not a hard rejection, since OCR/LLM output can be imperfect and the review step is the correction path).

**Relationships:** Single-table design; no related entities needed for v1 (no multi-user ownership, no image blob storage in DB).

### Example row (JSON view)
```json
{
  "id": "b3f1c2a0-1111-4a22-9c33-abcdef123456",
  "status": "confirmed",
  "name_value": "Jane Doe",
  "name_status": "confirmed",
  "email_value": "jane@acme.com",
  "email_status": "confirmed",
  "raw_ocr_text": "Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100",
  "qr_detected": false,
  "qr_decoded": false,
  "created_at": "2026-07-26T10:00:00Z",
  "updated_at": "2026-07-26T10:00:00Z"
}
```

## Error Handling

| Error Type | Trigger | HTTP Code | error_code | System Action |
|------------|---------|-----------|------------|----------------|
| Unsupported format | Req 1.3 | 400 | `unsupported_format` | Reject before processing |
| File too large | Req 1.2 | 413 | `file_too_large` | Reject before processing |
| Corrupted/empty file | Req 1.4 | 400 | `invalid_image` | Reject before processing |
| Not a business card (shape) | Req 2.2 | 422 | `not_a_business_card` (stage: shape) | No DB write |
| Not a business card (text) | Req 2.4 | 422 | `not_a_business_card` (stage: text_pattern) | No DB write |
| OCR produced no text | Req 3.3 | 422 | `ocr_no_text` | No DB write |
| LLM/extraction service unavailable | Req 4.5 | 503 | `extraction_service_unavailable` | No DB write, no partial record |
| Record not found | Req 8.3 | 404 | `record_not_found` | — |
| Database write failure | Req 7.3 | 500 | `persistence_failed` | Log, no success response |
| Invalid review resolution payload | Req 6.6 | 400 | `invalid_review_payload` | Return field-level validation errors |

### Recovery Mechanisms
- Pipeline stages fail fast and raise typed exceptions caught by a FastAPI exception handler that maps them to the table above — no silent partial writes (aligns with the "no orphaned partial records" NFR).
- llama.cpp model is loaded once at app startup (not per-request) to avoid cold-load latency inside the 30s budget where possible; if load fails at startup, the app still starts but `/cards` returns `503 extraction_service_unavailable` until an operator fixes the model path/config.

## Testing Strategy

### Unit Testing
- `CardClassifier`: shape-check and text-pattern-check logic with synthetic OpenCV inputs and mocked OCR text.
- `QrService.parse_payload`: vCard/MECARD/delimited parsing against fixture payload strings.
- `ReconciliationService`: field comparison matrix (match, mismatch, missing-QR, case/whitespace normalization) — table-driven tests covering every `FieldStatus` outcome.
- `LlmExtractionService`: grammar/schema conformance using a small local test model or a mocked llama.cpp binding.

### Integration Testing
- Full `POST /cards` flow against a test PostgreSQL instance (e.g., via `testcontainers` or a dedicated test DB), using fixture business-card images (with and without QR codes, valid and invalid cards).
- `GET /cards/{id}`, `GET /cards`, `PATCH /cards/{id}/review` against seeded records.

### End-to-End Testing
- Critical path: upload real sample business card image → verify persisted record fields → resolve a `needs_review` record → verify status transitions to `confirmed`.
- Negative path: upload a non-card image (e.g., a landscape photo) → verify `422 not_a_business_card` and no DB row created.

### Performance Testing
- Measure end-to-end pipeline latency for a representative set of sample images to validate the 30s NFR budget, with the LLM model pre-warmed at startup.
