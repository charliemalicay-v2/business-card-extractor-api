from supabase import create_client

from app.services.exceptions import ImageStorageError


class SupabaseImageStorage:
    def __init__(
        self,
        supabase_url: str,
        service_key: str,
        bucket: str,
        public: bool,
        url_ttl_seconds: int,
    ):
        self._bucket = bucket
        self._public = public
        self._url_ttl_seconds = url_ttl_seconds
        self._client = create_client(supabase_url, service_key)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        storage = self._client.storage.from_(self._bucket)
        try:
            storage.upload(key, data, {"content-type": content_type})
        except Exception as exc:  # supabase-py raises its own StorageException subclasses
            try:
                storage.update(key, data, {"content-type": content_type})
            except Exception as retry_exc:
                raise ImageStorageError(
                    f"Failed to upload image {key!r} to Supabase Storage: {retry_exc}"
                ) from exc

    def delete(self, key: str) -> None:
        try:
            self._client.storage.from_(self._bucket).remove([key])
        except Exception:
            # delete() must be idempotent: a missing key is not a failure.
            return

    def url(self, key: str) -> str:
        storage = self._client.storage.from_(self._bucket)
        try:
            if self._public:
                return storage.get_public_url(key)
            signed = storage.create_signed_url(key, self._url_ttl_seconds)
            return signed["signedURL"]
        except Exception as exc:
            raise ImageStorageError(f"Failed to build Supabase URL for {key!r}: {exc}") from exc
