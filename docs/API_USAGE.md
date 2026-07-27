# API Usage Guide

Base URL (local dev): `http://localhost:8000`

Interactive OpenAPI docs are available at `/docs` once the server is running (see
[README.md](../README.md) for setup).

No authentication is required — this is a single-user/internal tool (see
[requirements.md](../.kiro/specs/business-card-extractor/requirements.md)).

## Endpoints at a glance

| Method | Path                    | Purpose                                              |
|--------|-------------------------|-------------------------------------------------------|
| POST   | `/cards`                | Upload a business card image, run the full pipeline   |
| GET    | `/cards/{id}`           | Retrieve one record (full detail, incl. raw OCR text) |
| GET    | `/cards`                | List records (filter by status, paginated)            |
| PATCH  | `/cards/{id}/review`    | Resolve a record stuck in `needs_review`               |

## Core concepts

Every upload produces a **record** with an overall `status`:

- `confirmed` — all fields are either agreed upon by OCR/LLM and QR, or only one source
  was available (no conflict to resolve).
- `needs_review` — at least one field has conflicting values from OCR/LLM vs. the QR
  code, and needs a human decision before it's considered final.

Each of the five required fields (`name`, `position`, `company`, `email`, `phone`) carries
its own per-field `status`:

- `confirmed` — OCR/LLM and QR agree (or a review resolved a conflict).
- `conflict` — OCR/LLM and QR disagree; `value` is `null` until resolved.
- `unverified` — only one source had data for this field (nothing to cross-check against).

---

## Scenario 1: Upload a business card with no QR code

The common case — a card with no QR code. Every field falls back to `unverified` (only
one source, OCR/LLM, was available) and the record is auto-confirmed.

```bash
curl -X POST http://localhost:8000/cards \
  -F "file=@jane_doe_card.jpg;type=image/jpeg"
```

**Response — `201 Created`:**

```json
{
  "id": "b3f1c2a0-1111-4a22-9c33-abcdef123456",
  "status": "confirmed",
  "fields": {
    "name":     { "value": "Jane Doe",        "status": "unverified", "ocr_llm_value": "Jane Doe",        "qr_value": null },
    "position": { "value": "Sales Manager",   "status": "unverified", "ocr_llm_value": "Sales Manager",   "qr_value": null },
    "company":  { "value": "Acme Corp",       "status": "unverified", "ocr_llm_value": "Acme Corp",       "qr_value": null },
    "email":    { "value": "jane@acme.com",   "status": "unverified", "ocr_llm_value": "jane@acme.com",   "qr_value": null },
    "phone":    { "value": "+1-555-0100",     "status": "unverified", "ocr_llm_value": "+1-555-0100",     "qr_value": null }
  },
  "optional_fields": { "website": "acme.com" },
  "qr": { "detected": false, "decoded": false },
  "raw_ocr_text": "Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100",
  "created_at": "2026-07-27T10:00:00Z",
  "updated_at": "2026-07-27T10:00:00Z"
}
```

Nothing further to do — the record is already `confirmed`.

---

## Scenario 2: Upload a card with a QR code that agrees with the printed text

When a QR code is present and its data matches what OCR/LLM extracted, matching fields
become `confirmed` automatically.

```bash
curl -X POST http://localhost:8000/cards \
  -F "file=@jane_doe_card_with_qr.jpg;type=image/jpeg"
```

**Response — `201 Created`:**

```json
{
  "id": "c4a2d3b1-2222-4b33-a044-bcdef2345678",
  "status": "confirmed",
  "fields": {
    "name":    { "value": "Jane Doe",      "status": "confirmed", "ocr_llm_value": "Jane Doe",      "qr_value": "Jane Doe" },
    "company": { "value": "Acme Corp",     "status": "confirmed", "ocr_llm_value": "Acme Corp",     "qr_value": "Acme Corp" },
    "email":   { "value": "jane@acme.com", "status": "confirmed", "ocr_llm_value": "jane@acme.com", "qr_value": "jane@acme.com" }
  },
  "optional_fields": {},
  "qr": { "detected": true, "decoded": true },
  "raw_ocr_text": "...",
  "created_at": "2026-07-27T10:05:00Z",
  "updated_at": "2026-07-27T10:05:00Z"
}
```

(Field comparison is whitespace-normalized and case-insensitive, so minor OCR noise like
`"  jane   doe "` vs `"Jane Doe"` still counts as a match.)

---

## Scenario 3: Upload a card where the QR code disagrees — review workflow

This is the interesting case: the printed/OCR'd text and the QR code disagree on a
field (e.g. the QR encodes the full legal entity name while the printed card is
abbreviated). The record needs a human to pick the right value.

**Step 1 — upload:**

```bash
curl -X POST http://localhost:8000/cards \
  -F "file=@conflicting_card.jpg;type=image/jpeg"
```

**Response — `201 Created`, but `needs_review`:**

```json
{
  "id": "d5b3e4c2-3333-4c44-b155-cdef34567890",
  "status": "needs_review",
  "fields": {
    "name": { "value": "Jane Doe", "status": "confirmed", "ocr_llm_value": "Jane Doe", "qr_value": "Jane Doe" },
    "company": {
      "value": null,
      "status": "conflict",
      "ocr_llm_value": "Acme Corp",
      "qr_value": "Acme Corporation"
    },
    "email": { "value": "jane@acme.com", "status": "confirmed", "ocr_llm_value": "jane@acme.com", "qr_value": "jane@acme.com" }
  },
  "optional_fields": {},
  "qr": { "detected": true, "decoded": true },
  "raw_ocr_text": "...",
  "created_at": "2026-07-27T10:10:00Z",
  "updated_at": "2026-07-27T10:10:00Z"
}
```

Note `company.value` is `null` — there is no authoritative value yet. `ocr_llm_value`
and `qr_value` show both candidates so a client/operator can decide.

**Step 2 — an operator reviews the two candidate values and resolves it:**

```bash
curl -X PATCH http://localhost:8000/cards/d5b3e4c2-3333-4c44-b155-cdef34567890/review \
  -H "Content-Type: application/json" \
  -d '{"company": "Acme Corporation"}'
```

You aren't limited to picking one of the two candidates verbatim — any string is
accepted as the operator's final decision (e.g. a corrected spelling neither source got
right).

**Response — `200 OK`:**

```json
{
  "id": "d5b3e4c2-3333-4c44-b155-cdef34567890",
  "status": "confirmed",
  "fields": {
    "company": {
      "value": "Acme Corporation",
      "status": "confirmed",
      "ocr_llm_value": "Acme Corp",
      "qr_value": "Acme Corporation"
    }
  },
  "...": "other fields unchanged"
}
```

The overall record status flips to `confirmed` once every conflicting field has been
resolved (a `PATCH` only needs to include the fields you're resolving — omit fields
that weren't in conflict).

**Rejecting an invalid resolution attempt:**

```bash
# Trying to resolve a record that isn't pending review
curl -X PATCH http://localhost:8000/cards/<already-confirmed-id>/review \
  -H "Content-Type: application/json" -d '{"name": "Someone Else"}'
# -> 400 {"error_code": "invalid_review_payload", "message": "Record is not pending review."}

# Empty resolution payload
curl -X PATCH http://localhost:8000/cards/<needs-review-id>/review \
  -H "Content-Type: application/json" -d '{}'
# -> 400 {"error_code": "invalid_review_payload", "message": "At least one resolved field value must be provided."}
```

---

## Scenario 4: List and filter records

List all `needs_review` records that still need attention, most recent first, 10 per
page:

```bash
curl "http://localhost:8000/cards?status=needs_review&page=1&page_size=10"
```

**Response — `200 OK`:**

```json
{
  "items": [
    {
      "id": "d5b3e4c2-3333-4c44-b155-cdef34567890",
      "status": "needs_review",
      "fields": { "...": "..." },
      "optional_fields": {},
      "qr": { "detected": true, "decoded": true },
      "created_at": "2026-07-27T10:10:00Z",
      "updated_at": "2026-07-27T10:10:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

Note list items **omit** `raw_ocr_text` to keep list payloads lightweight — fetch
`GET /cards/{id}` for the full record including raw OCR text.

Omit `status` to list everything:

```bash
curl "http://localhost:8000/cards?page=1&page_size=20"
```

---

## Scenario 5: Retrieve a single record

```bash
curl http://localhost:8000/cards/b3f1c2a0-1111-4a22-9c33-abcdef123456
```

Returns the full `CardResponse` shown in Scenario 1, including `raw_ocr_text`.

If the id doesn't exist:

```bash
curl -i http://localhost:8000/cards/00000000-0000-0000-0000-000000000000
# -> 404 {"error_code": "record_not_found", "message": "No record found with id ..."}
```

---

## Error scenarios

| Trigger | HTTP status | `error_code` |
|---|---|---|
| Non-image / unsupported content-type file | 400 | `unsupported_format` |
| File exceeds `MAX_UPLOAD_SIZE_BYTES` (default 10MB) | 413 | `file_too_large` |
| Empty or corrupted file | 400 | `invalid_image` |
| Image doesn't look like a business card (shape or content check fails) | 422 | `not_a_business_card` (includes a `stage` field: `"shape"` or `"text_pattern"`) |
| OCR found no usable text | 422 | `ocr_no_text` |
| Local LLM model isn't loaded/available | 503 | `extraction_service_unavailable` |
| Record id doesn't exist | 404 | `record_not_found` |
| Review payload invalid (empty, or record not in `needs_review`) | 400 | `invalid_review_payload` |
| Database write failed | 500 | `persistence_failed` |

**Example — uploading a non-card image:**

```bash
curl -i -X POST http://localhost:8000/cards -F "file=@random_photo.jpg;type=image/jpeg"
```

```
HTTP/1.1 422 Unprocessable Content
{
  "error_code": "not_a_business_card",
  "message": "Image does not appear to be a business card.",
  "stage": "shape"
}
```

**Example — file too large:**

```bash
curl -i -X POST http://localhost:8000/cards -F "file=@huge_scan.png;type=image/png"
```

```
HTTP/1.1 413 Content Too Large
{"error_code": "file_too_large", "message": "File exceeds the maximum allowed size of 10485760 bytes."}
```

All error responses share this shape — `error_code` is stable and meant to be matched
programmatically; `message` is a human-readable string and (per this API's error
handling policy) never includes internal details like file paths or stack traces.

---

## Quick reference: full curl cheat sheet

```bash
# Upload
curl -X POST http://localhost:8000/cards -F "file=@card.jpg;type=image/jpeg"

# Get one
curl http://localhost:8000/cards/<id>

# List (all, or filtered/paginated)
curl http://localhost:8000/cards
curl "http://localhost:8000/cards?status=needs_review&page=1&page_size=10"

# Resolve a review conflict
curl -X PATCH http://localhost:8000/cards/<id>/review \
  -H "Content-Type: application/json" \
  -d '{"company": "Corrected Value"}'
```
