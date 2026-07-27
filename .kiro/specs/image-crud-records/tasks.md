# Tasks: Image Storage & Full CRUD for Business Card Records

- [x] 1. Configuration and schema foundation
- [x] 1.1 Add image storage settings to `app/config.py`
  - `image_storage_backend` (`local`/`s3`/`supabase`), `image_storage_local_dir`,
    `image_storage_url_ttl_seconds`, `aws_s3_bucket`, `aws_region`, `aws_access_key_id`,
    `aws_secret_access_key`, `supabase_url`, `supabase_service_key`, `supabase_storage_bucket`,
    `supabase_storage_public`
  - Document all new vars in `.env.example`
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
- [x] 1.2 Add `image_storage_key` column via Alembic migration
  - Nullable `String` column on `business_cards`; no backfill (existing rows get `NULL`)
  - _Requirements: 6.1, 6.2_

- [x] 2. `ImageStorage` abstraction
- [x] 2.1 Define `ImageStorage` protocol in `app/services/image_storage/base.py`
  - `put(key, data, content_type) -> None`, `delete(key) -> None` (idempotent),
    `url(key) -> str`
  - Add `ImageStorageError` to `app/services/exceptions.py`
  - _Requirements: 1.7_
- [x] 2.2 Implement `LocalImageStorage` (`app/services/image_storage/local_storage.py`)
  - `put`/`delete` against `image_storage_local_dir`; `url()` raises `NotImplementedError`
    (callers use the record-id-based route instead, per design)
  - Unit tests against a tmp dir: put writes file, delete removes it, delete on missing key is a
    no-op
  - _Requirements: 1.2_
- [x] 2.3 Implement `S3ImageStorage` (`app/services/image_storage/s3_storage.py`)
  - boto3 client from settings; `put_object`/`delete_object`/`generate_presigned_url`
  - Unit tests with `botocore.stub.Stubber`: successful put/delete/url, and a failed put raises
    `ImageStorageError`
  - _Requirements: 1.3, 1.6_
- [x] 2.4 Implement `SupabaseImageStorage` (`app/services/image_storage/supabase_storage.py`)
  - Upload/remove/public-or-signed-url per `supabase_storage_public` setting
  - Unit tests with a mocked Supabase storage client: put/delete/url in both public and signed
    modes, failed put raises `ImageStorageError`
  - _Requirements: 1.4, 1.6_
- [x] 2.5 Add `get_image_storage()` factory and wire into `app/api/dependencies.py`
  - Raises clearly on unrecognized `image_storage_backend` at construction time
  - Unit test: monkeypatch `settings.image_storage_backend` through `local`/`s3`/`supabase`/
    invalid and assert correct type / raise
  - _Requirements: 1.1, 1.5_

- [x] 3. Persist images on create
- [x] 3.1 Update `CardProcessingService.process()` to upload the image
  - Generate a `uuid4`-based storage key with the original extension, call
    `image_storage.put(...)` before building the record, set `image_storage_key` on the record
  - On `ImageStorageError`, propagate before any DB write (no partial record)
  - _Requirements: 3.1, 3.2, 1.6_
- [x] 3.2 Integration test: create with `LocalImageStorage` against a tmp dir
  - Assert the file exists after `POST /cards` and the record's `image_storage_key` is set
  - _Requirements: 3.1, 3.2_

- [x] 4. Expose `image_url` in responses
- [x] 4.1 Add `build_image_url(record)` helper (special-cases `local` -> `/cards/{id}/image`,
  else delegates to `image_storage.url(key)`; returns `None` when `image_storage_key is None`)
  - _Requirements: 2.1, 2.2, 2.5, 6.1_
- [x] 4.2 Add `image_url` field to `CardResponse` and `CardListItemResponse`, wire through
  `from_record()`
  - _Requirements: 2.1, 2.2, 3.3_
- [x] 4.3 API tests: `GET /cards/{id}` and `GET /cards` include correct `image_url` for local/S3/
  Supabase-configured backends (S3/Supabase mocked), and `null` for a record with no
  `image_storage_key`
  - _Requirements: 2.1, 2.2, 2.5_

- [ ] 5. Local image-serving endpoint
- [ ] 5.1 Add `GET /cards/{id}/image` to `app/api/cards.py`
  - 404 if record missing, backend isn't `local`, or `image_storage_key` is `None`; otherwise
    `FileResponse` with content-type guessed from filename extension
  - _Requirements: 2.3_
- [ ] 5.2 API tests: 200 with correct bytes/content-type for an existing local image; 404 for
  missing record, missing image, and non-local backend
  - _Requirements: 2.3, 2.5_

- [ ] 6. Update endpoint (`PATCH /cards/{id}`)
- [ ] 6.1 Add `CardUpdateRequest` schema (all fields optional) to `app/schemas/response.py` (or a
  new `app/schemas/request.py` if cleaner alongside existing schemas)
  - _Requirements: 4.1, 4.4_
- [ ] 6.2 Add `CardRepository.update(card_id, fields: dict) -> BusinessCardRecord`
  - Applies field updates, commits, refreshes, relies on existing `onupdate=func.now()` for
    `updated_at`
  - _Requirements: 4.1, 4.6_
- [ ] 6.3 Implement `PATCH /cards/{id}` route
  - Multipart: optional `file: UploadFile | None` + `CardUpdateRequest` form fields
  - 404 `record_not_found` if missing; 400 `invalid_update_payload` if neither fields nor file
    given; existing content-type/size validation reused for the file path
  - If a new file is given: validate -> upload new key -> apply DB update (fields + new
    `image_storage_key`) -> on commit success, delete old key via `image_storage.delete()`
  - On `ImageStorageError` during upload, abort before any DB write
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
- [ ] 6.4 API tests for `PATCH /cards/{id}`
  - Field-only update, image-replace update (old file actually removed from local storage),
    404, empty-payload 400, invalid field value 400, verify `PATCH /cards/{id}/review` still
    behaves independently
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7_

- [ ] 7. Delete endpoint (`DELETE /cards/{id}`)
- [ ] 7.1 Add `CardRepository.delete(card_id) -> None`
  - _Requirements: 5.1_
- [ ] 7.2 Implement `DELETE /cards/{id}` route
  - 404 `record_not_found` if missing; else best-effort `image_storage.delete()` (log failures,
    don't raise per design Decision 1), then `repository.delete()`, respond `204`
  - _Requirements: 5.1, 5.2, 5.3_
- [ ] 7.3 API tests for `DELETE /cards/{id}`
  - 204 on success, subsequent `GET` returns 404, 404 for already-missing id, delete still
    succeeds (204) when the storage delete is forced to fail (mock raises)
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 8. Exception handling wiring
- [x] 8.1 Register `ImageStorageError` -> `502 image_storage_unavailable` in
  `app/api/exception_handlers.py`, following the existing pattern for `NotABusinessCardError`
  - Landed early (PR #8 follow-up) since `build_image_url()` (task 4) already made
    `ImageStorageError` reachable from `GET`/list read paths, not just create
  - _Requirements: 1.6_

- [ ] 9. Full regression pass
- [ ] 9.1 Run the full existing suite plus all new tests; fix any response-shape regressions in
  existing create/list/get/review tests caused by the new `image_url` field
  - _Requirements: Non-Functional Notes (existing suite must keep passing)_
- [ ] 9.2 Update README/API usage docs and Postman collection for the two new endpoints and the
  new `image_url` response field
  - _Requirements: 2.1, 2.2, 4.*, 5.*_
