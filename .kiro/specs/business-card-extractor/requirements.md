# Requirements Document: Business Card Extractor API

## Overview
A REST API backend (Python + FastAPI) that accepts an uploaded image of a business card, validates it is indeed a business card, extracts contact data via OCR (Tesseract) and OpenCV, uses a local LLM (llama.cpp) to structure the extracted text into fields (Name, Position, Company, Email, Phone Number, plus optional fields), reads and cross-checks any QR code present on the card, reconciles discrepancies via a review step, and persists the final record to a local PostgreSQL database. No authentication is required (internal/local tool). This is a single-tenant, locally-run system — no Supabase/cloud dependency for this feature.

## User Roles
- **API Client / Operator**: The person or system calling the API to upload business card images and retrieve/review/confirm extracted records. No login required; trusted local/internal usage.

## Requirements

### Requirement 1: Image Upload
**User Story:** As an operator, I want to upload a business card image, so that the system can extract contact data from it.

**Acceptance Criteria:**
1. WHEN operator uploads a file with a supported image format (JPEG, PNG) THEN system SHALL accept the file and begin processing.
2. WHEN operator uploads a file exceeding the maximum size (10MB) THEN system SHALL reject the upload with a "file too large" error.
3. WHEN operator uploads a file with an unsupported format THEN system SHALL reject the upload with an "unsupported format" error listing allowed types.
4. WHEN operator uploads an empty or corrupted file THEN system SHALL reject the upload with a descriptive error.
5. WHEN upload is accepted THEN system SHALL return a unique record/job identifier for tracking processing status.

### Requirement 2: Business Card Validation
**User Story:** As an operator, I want the system to verify the uploaded image is actually a business card, so that invalid images are rejected early instead of wasting processing time.

**Acceptance Criteria:**
1. WHEN an image is uploaded THEN system SHALL run an OpenCV-based shape/aspect-ratio/edge-detection heuristic to pre-check whether the image resembles a business card.
2. WHEN the OpenCV pre-check fails THEN system SHALL throw a validation error ("not a business card") and SHALL NOT proceed to OCR/LLM processing.
3. WHEN the OpenCV pre-check passes THEN system SHALL run OCR and check the extracted text for business-card-like patterns (e.g., presence of email-like or phone-like tokens).
4. IF the OCR text pattern check fails after passing the OpenCV check THEN system SHALL throw a validation error ("not a business card") and SHALL NOT proceed to LLM structuring.
5. WHEN both the OpenCV check and OCR text pattern check pass THEN system SHALL mark the image as a valid business card and proceed to data extraction.
6. WHEN validation fails for any reason THEN system SHALL respond with an HTTP 4xx error and a machine-readable reason code, and SHALL NOT create a database record.

### Requirement 3: OCR Text Extraction
**User Story:** As an operator, I want the system to extract raw text from a validated business card image, so that structured data can be derived from it.

**Acceptance Criteria:**
1. WHEN an image passes validation THEN system SHALL preprocess the image with OpenCV (e.g., deskew, denoise, contrast enhancement) before OCR.
2. WHEN preprocessing completes THEN system SHALL run Tesseract OCR on the processed image and capture the raw extracted text.
3. IF OCR produces no usable text (empty/near-empty result) THEN system SHALL throw an error and mark the record as failed with reason "ocr_no_text".
4. WHEN OCR completes successfully THEN system SHALL store the raw OCR text alongside the record for traceability.

### Requirement 4: LLM-Based Field Extraction
**User Story:** As an operator, I want the raw OCR text turned into structured fields, so that I get usable contact records instead of unstructured text.

**Acceptance Criteria:**
1. WHEN raw OCR text is available THEN system SHALL invoke a local llama.cpp model to identify and extract: Name, Position, Company, Email, Phone Number.
2. WHEN the LLM identifies additional information not in the required field set (e.g., address, website, fax) THEN system SHALL store it as optional/supplementary data.
3. IF the LLM cannot confidently identify one or more required fields THEN system SHALL store the field as null/empty and flag the record as incomplete rather than failing the whole request.
4. WHEN LLM extraction completes THEN system SHALL store the structured field values along with a per-field confidence indicator (if the model provides one) or a default confidence level.
5. IF the llama.cpp model is unavailable or errors THEN system SHALL fail the request with a clear "extraction service unavailable" error and SHALL NOT create a partial record silently.

### Requirement 5: QR Code Detection and Extraction
**User Story:** As an operator, I want QR code data on the business card extracted, so that it can be used to verify the OCR/LLM results.

**Acceptance Criteria:**
1. WHEN a validated image is processed THEN system SHALL attempt to detect a QR code using OpenCV's QR code detector.
2. IF a QR code is detected THEN system SHALL decode its contents and attempt to parse it into the same field set (Name, Position, Company, Email, Phone Number) using a best-effort parser (e.g., vCard/MECARD format or delimited text).
3. IF no QR code is detected on the image THEN system SHALL proceed without QR data and mark the record as having no QR source.
4. IF a QR code is detected but cannot be decoded or parsed THEN system SHALL record the raw decode failure and proceed using OCR/LLM data only, marking QR status as "unreadable".

### Requirement 6: Data Reconciliation and Review
**User Story:** As an operator, I want conflicting OCR/LLM and QR data flagged for review, so that I can confirm the correct value instead of the system guessing incorrectly.

**Acceptance Criteria:**
1. WHEN both OCR/LLM data and QR data are available for a field THEN system SHALL compare the two values for that field.
2. IF the OCR/LLM value and QR value for a field match (case-insensitive, whitespace-normalized) THEN system SHALL mark that field as confirmed and use the matched value.
3. IF the OCR/LLM value and QR value for a field differ THEN system SHALL mark that field as "conflict", store both candidate values, and set the overall record status to "needs_review".
4. IF QR data is unavailable for a field THEN system SHALL use the OCR/LLM value and mark the field as "unverified" (not conflicting, but not cross-checked).
5. WHEN a record status is "needs_review" THEN system SHALL NOT auto-finalize the record; it SHALL remain in a pending state until an operator resolves the conflicts.
6. WHEN an operator submits a resolution for a "needs_review" record (selecting or editing final field values) THEN system SHALL update the record with the resolved values and set status to "confirmed".
7. WHEN a record has no conflicts (all fields confirmed or unverified) THEN system SHALL set status to "confirmed" automatically without requiring manual review.

### Requirement 7: Data Persistence
**User Story:** As an operator, I want finalized business card records saved to the database, so that I can retrieve and query them later.

**Acceptance Criteria:**
1. WHEN a record reaches "confirmed" status THEN system SHALL persist the record (required fields, optional fields, QR data, raw OCR text, validation/reconciliation metadata) to the local PostgreSQL database.
2. WHEN a record is in "needs_review" status THEN system SHALL still persist it (as a pending record) so it is not lost, but SHALL mark it clearly as unconfirmed.
3. WHEN persistence fails (e.g., database unavailable) THEN system SHALL return an HTTP 5xx error and SHALL NOT report success to the client.
4. WHEN a record is successfully persisted THEN system SHALL return the stored record including its identifier, status, and field values.

### Requirement 8: Record Retrieval
**User Story:** As an operator, I want to retrieve previously processed business card records, so that I can review, audit, or export them.

**Acceptance Criteria:**
1. WHEN operator requests a record by identifier THEN system SHALL return the full record including field values, source (OCR/LLM/QR), status, and raw OCR text.
2. WHEN operator lists records THEN system SHALL support filtering by status (e.g., "needs_review", "confirmed") and pagination.
3. IF a requested record identifier does not exist THEN system SHALL return an HTTP 404 error.

## Non-Functional Requirements
- **Performance:** WHEN an image is uploaded THEN system SHALL complete validation, OCR, LLM extraction, and QR reconciliation within 30 seconds for a typical business card image, excluding cases where the local LLM model is cold-loading.
- **Local Execution:** OCR (Tesseract), OpenCV, and the LLM (llama.cpp) SHALL run entirely on local infrastructure with no external network calls required for core processing.
- **Data Integrity:** Raw OCR text and QR raw payload SHALL be retained for every processed record to support auditing and re-processing.
- **Reliability:** WHEN any processing stage fails THEN system SHALL return a clear, machine-readable error and SHALL leave no orphaned partial records in an ambiguous state.

## Out of Scope
- User authentication/authorization (not required for this MVP; single-user/internal tool).
- Supabase/cloud database integration (local PostgreSQL only for this feature).
- Batch/bulk upload of multiple images in a single request.
- Multi-language OCR support beyond Tesseract's default configured language(s).
- Editing/versioning history of resolved records beyond the current confirmed values.

## Open Questions
- What confidence threshold (if any) should trigger "needs_review" even when OCR/LLM and QR agree, based on low OCR/LLM confidence alone?
- Should there be a retention/cleanup policy for uploaded image files after processing?
