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
