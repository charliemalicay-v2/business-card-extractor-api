# Requirements: Image Storage & Full CRUD for Business Card Records

## Background

Today, `POST /cards` extracts fields from an uploaded image but only stores the original
`image_filename` as a string on the `business_cards` row (`app/models/business_card.py:54`) — the
actual image bytes are discarded after processing (`app/services/card_processing_service.py`).
There is also no way to update a record's stored fields directly, replace/remove its image, or
delete a record; the only existing "write" endpoints are `POST /cards` (create) and
`PATCH /cards/{id}/review` (resolve a conflicted field).

This spec adds:
1. Real image persistence via a pluggable storage backend (local disk, AWS S3, or Supabase
   Storage, selected by configuration).
2. An image URL/reference in record responses so a frontend can display the card image in a
   record list and detail view.
3. Full CRUD on business card records: Create (existing, extended to persist the image),
   Read (existing), Update (new — edit field values and/or replace the image), Delete (new —
   removes the DB row and the stored image).

## Glossary

- **Record**: A row in `business_cards`, representing one processed business card.
- **Storage backend**: The active image storage implementation (local filesystem, AWS S3, or
  Supabase Storage), chosen via a single configuration value.
- **Image reference**: A stable identifier (storage key/path) persisted on the record, from which
  a retrievable URL can be derived at read time.

## Requirements

### Requirement 1: Configurable image storage backend

**User Story:** As the API operator, I want to choose where card images are physically stored
(local disk, S3, or Supabase), so I can deploy the same codebase across different environments
without code changes.

**Acceptance Criteria:**
1. WHEN the app starts THEN system SHALL read a single configuration value (e.g.
   `IMAGE_STORAGE_BACKEND`) that selects exactly one of `local`, `s3`, or `supabase`.
2. IF `IMAGE_STORAGE_BACKEND` is `local` THEN system SHALL store uploaded images under a
   configured local directory (e.g. `IMAGE_STORAGE_LOCAL_DIR`) and serve them back through the
   API rather than assuming they're web-reachable directly.
3. IF `IMAGE_STORAGE_BACKEND` is `s3` THEN system SHALL upload images to a configured S3 bucket
   (bucket name, region, and credentials supplied via configuration/environment) and be able to
   produce a retrievable URL for a stored image (e.g. a pre-signed URL).
4. IF `IMAGE_STORAGE_BACKEND` is `supabase` THEN system SHALL upload images to a configured
   Supabase Storage bucket (project URL, service key, bucket name via configuration) and be able
   to produce a retrievable URL for a stored image.
5. IF `IMAGE_STORAGE_BACKEND` is set to a value other than `local`, `s3`, or `supabase` THEN
   system SHALL fail fast at startup with a clear configuration error.
6. WHEN a storage backend upload fails (network error, auth error, bucket missing, etc.) during
   record create or update THEN system SHALL NOT persist a partially-written record, and SHALL
   return a 502/503-class error indicating the image could not be stored.
7. All three backends SHALL be implemented behind one common interface, so the rest of the
   application (services, API routes) is not aware of which backend is active.

### Requirement 2: Image displayed in record list and detail views

**User Story:** As an API consumer building a frontend, I want each record (in both the list and
single-record views) to include a way to display the card's image, so users can visually confirm
extracted data against the source photo.

**Acceptance Criteria:**
1. WHEN a client calls `GET /cards` THEN each item in the response SHALL include an image URL (or
   null if the record has no stored image).
2. WHEN a client calls `GET /cards/{id}` THEN the response SHALL include an image URL (or null if
   the record has no stored image).
3. IF the active backend is `local` THEN the returned image URL SHALL point to an API endpoint
   that streams the image bytes with the correct content type.
4. IF the active backend is `s3` or `supabase` THEN the returned image URL SHALL be directly
   fetchable by a browser (e.g. a pre-signed or public URL), without requiring the client to hold
   storage credentials.
5. WHEN a record has no image (e.g. created before this feature, or image storage failed
   non-fatally in a legacy record) THEN the image URL field SHALL be `null` rather than causing an
   error.

### Requirement 3: Create persists the uploaded image

**User Story:** As an API consumer, I want the image I upload in `POST /cards` to actually be
saved, so it can be displayed and retrieved later.

**Acceptance Criteria:**
1. WHEN `POST /cards` successfully processes an uploaded image THEN system SHALL store the
   original image bytes in the active storage backend before returning a response.
2. WHEN the record is persisted THEN system SHALL save the storage backend's image reference
   (key/path) on the record, replacing the current filename-only field.
3. WHEN `POST /cards` responds with `201` THEN the response body SHALL include the image URL as
   described in Requirement 2.

### Requirement 4: Update a record (fields and/or image)

**User Story:** As an API consumer, I want to update a record's field values and/or replace its
image after creation, so I can correct data or re-scan a card without deleting and recreating the
record.

**Acceptance Criteria:**
1. WHEN a client calls `PUT /cards/{id}` (or `PATCH`, for partial updates) with one or more field
   values (e.g. `name_value`, `position_value`, `company_value`, `email_value`, `phone_value`,
   `optional_fields`) THEN system SHALL update those fields on the record and return the updated
   record.
2. WHEN a client calls the update endpoint with a new image file THEN system SHALL upload the new
   image to the active storage backend, update the record's image reference to point to it, and
   delete the previous stored image from the backend.
3. IF the record does not exist THEN system SHALL respond `404 record_not_found`.
4. IF the update payload contains no recognized fields and no image THEN system SHALL respond
   `400 invalid_update_payload`.
5. IF an updated field value fails existing validation constraints (e.g. status enum values) THEN
   system SHALL respond `400` with a descriptive error and SHALL NOT partially apply the update.
6. WHEN an update succeeds THEN system SHALL update the record's `updated_at` timestamp.
7. This update endpoint is distinct from the existing `PATCH /cards/{id}/review` endpoint (which
   resolves field conflicts); both SHALL continue to work without interfering with each other.

### Requirement 5: Delete a record

**User Story:** As an API consumer, I want to delete a record I no longer need, so stale or
incorrect entries don't clutter the record list.

**Acceptance Criteria:**
1. WHEN a client calls `DELETE /cards/{id}` for an existing record THEN system SHALL delete the
   record from the database AND delete its associated image from the active storage backend, then
   respond `204 No Content`.
2. IF the record does not exist THEN system SHALL respond `404 record_not_found`.
3. IF deleting the image from the storage backend fails THEN system SHALL still delete (or SHALL
   NOT delete — *needs a decision, see Open Questions*) the database row, and SHALL surface the
   storage failure distinctly from a not-found error.
4. WHEN a record is deleted THEN subsequent `GET /cards/{id}` for that id SHALL respond `404`.

### Requirement 6: Migration of existing data

**User Story:** As the API operator, I want existing records created before this feature to keep
working, so the rollout doesn't break the current dataset.

**Acceptance Criteria:**
1. WHEN this feature is deployed against a database with existing `business_cards` rows that only
   have `image_filename` set (no actual stored image) THEN system SHALL treat their image URL as
   `null` rather than erroring.
2. WHEN the schema migration runs THEN system SHALL add whatever new column(s) are needed for the
   image storage reference without dropping existing data.

## Non-Functional Notes

- Image uploads must continue to respect existing `max_upload_size_bytes` and
  `allowed_image_content_types` settings for both create and update.
- Storage backend credentials (S3 keys, Supabase service key) must be supplied via environment
  configuration only, never hard-coded or logged.
- The 80-test existing suite's create/read/list/review flows must keep passing.

## Open Questions

1. **Delete-on-storage-failure ordering (Req 5.3):** if the storage delete fails, should the DB
   row still be removed (image becomes an orphaned blob) or should the whole delete be aborted
   (record persists so the operation can be retried)? Needs a decision before design.
2. **Update via `PUT` vs `PATCH`:** should Requirement 4 use `PUT /cards/{id}` (full replace
   semantics) or `PATCH /cards/{id}` (partial update, matching the existing review endpoint's
   verb)? Recommend `PATCH` for consistency with `PATCH /cards/{id}/review`, but confirm.
3. **Local backend URL exposure:** for the `local` backend, should the image-serving endpoint be
   public/unauthenticated (e.g. `GET /cards/{id}/image`) or should it require the same auth as
   the rest of the API (note: this API currently appears to have no auth layer at all)?
4. **Multi-backend migration:** is switching `IMAGE_STORAGE_BACKEND` after records already exist
   under a different backend in scope (i.e. do we need a migration/backfill tool), or is that
   explicitly out of scope for this spec?
