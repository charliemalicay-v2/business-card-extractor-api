# business-card-extractor-api

REST API that extracts structured contact data (name, position, company, email, phone) from
business card images, using OpenCV + Tesseract OCR, QR code detection, and a locally-run
llama.cpp model, with reconciliation between OCR/LLM and QR-derived data.

See [.kiro/specs/business-card-extractor/](.kiro/specs/business-card-extractor/) for the full
requirements, design, and implementation task list.

## Prerequisites

- Python 3.11+
- [Docker](https://www.docker.com/) (for local PostgreSQL)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) binary installed and on `PATH`
  - Windows: `winget install --id UB-Mannheim.TesseractOCR`
  - Debian/Ubuntu (including WSL): `sudo apt-get install tesseract-ocr`
- A C++ toolchain + `cmake` (needed to build `llama-cpp-python` from source)
  - Debian/Ubuntu (including WSL): `sudo apt-get install build-essential cmake`
  - Windows: install Visual Studio Build Tools (C++ workload), or install
    `llama-cpp-python` from a prebuilt wheel index instead of building from source
- A local GGUF model file for `llama-cpp-python` (e.g. a small instruct model in the 2-5GB
  range, such as `Qwen2.5-3B-Instruct-Q4_K_M.gguf` from Hugging Face)

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set LLM_MODEL_PATH to your downloaded GGUF file, adjust DATABASE_URL if needed

docker compose up -d          # starts local Postgres
alembic upgrade head          # creates the business_cards table
```

## Running the API

```bash
uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- See [docs/API_USAGE.md](docs/API_USAGE.md) for endpoint reference and worked usage
  scenarios (upload, review-conflict resolution, listing, error handling).
- A ready-to-import Postman collection is available at
  [postman/business-card-extractor-api.postman_collection.json](postman/business-card-extractor-api.postman_collection.json),
  organized into **Health**, **Cards - Upload**, **Cards - Retrieval**, and
  **Cards - Review** folders, with test scripts and a `card_id` variable that auto-chains
  between requests. Import it into Postman and set the `base_url` collection variable if
  not running on `localhost:8000`.

If the LLM model fails to load at startup (e.g. `LLM_MODEL_PATH` not set or the model file is
missing), the app still starts and serves requests, but `POST /cards` will return `503
extraction_service_unavailable` until the model is available.

## Running tests

```bash
pytest
```

Integration and end-to-end tests require the local Postgres container from `docker compose up
-d` to be running. Some tests exercise real OCR/LLM behavior only when Tesseract and a real GGUF
model are actually available in the environment; otherwise those dependencies are faked for
unit-test isolation (see `.kiro/specs/business-card-extractor/tasks.md` for details on what has
and hasn't been verified against real dependencies).

## Release Notes

### 0.3.1 ([#5](../../pull/5))
- Enabled CORS so a browser frontend can call the API: allowed origins are configured via the
  `CORS_ALLOWED_ORIGINS` env var (default `http://localhost:3000`), with allowed methods/headers
  narrowed instead of wildcarded.
- Added unit tests covering `cors_origins` parsing and documented the new env var in
  `.env.example`.

### 0.3.0 ([#3](../../pull/3))
- Fixed the `POST /cards` shape-classification check incorrectly rejecting valid business card
  photos: `check_shape()` now unions the bounding boxes of all detected contours instead of
  relying on the single largest one, and falls back to the raw image dimensions when no contours
  are detected at all.
- Added regression tests covering fragmented card outlines and the no-contours fallback path.

### 0.2.0 ([#2](../../pull/2))
- Implemented the full extraction pipeline: image upload -> OpenCV/Tesseract OCR + classification
  -> QR detection/parsing -> local llama.cpp field extraction -> reconciliation -> PostgreSQL
  persistence.
- Implemented the REST API: `POST /cards`, `GET /cards/{id}`, `GET /cards`,
  `PATCH /cards/{id}/review`.
- Added the Alembic migration for the `business_cards` table, Docker Compose for local Postgres,
  and 80 passing tests (unit, integration against real Postgres, and e2e fixture tests).
- Sanitized error responses and fixed remaining review comments (CI, docs, list payload,
  healthcheck).

### 0.1.0 ([#1](../../pull/1))
- Added the spec-driven planning docs for the Business Card Extractor API: EARS-format
  requirements, FastAPI/OpenCV/Tesseract/llama.cpp architecture design, and a sequenced
  implementation task list.
