from storage3.exceptions import StorageApiError
from supabase import create_client

from app.services.exceptions import ImageStorageError

_DUPLICATE_CODES = {"Duplicate", "42P07"}
_NOT_FOUND_CODES = {"NotFound", "not_found", "404"}


def _is_duplicate_error(exc: StorageApiError) -> bool:
    return str(exc.status) == "409" or exc.code in _DUPLICATE_CODES


def _is_not_found_error(exc: StorageApiError) -> bool:
    return str(exc.status) == "404" or exc.code in _NOT_FOUND_CODES


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
        except StorageApiError as exc:
            if not _is_duplicate_error(exc):
                raise ImageStorageError(f"Failed to upload image {key!r} to Supabase Storage: {exc}") from exc
            try:
                storage.update(key, data, {"content-type": content_type})
            except StorageApiError as retry_exc:
                raise ImageStorageError(
                    f"Failed to upload image {key!r} to Supabase Storage: {retry_exc}"
                ) from retry_exc

    def delete(self, key: str) -> None:
        try:
            self._client.storage.from_(self._bucket).remove([key])
        except StorageApiError as exc:
            if not _is_not_found_error(exc):
                raise ImageStorageError(f"Failed to delete image {key!r} from Supabase Storage: {exc}") from exc
            # delete() must be idempotent: a missing key is not a failure.

    def url(self, key: str) -> str:
        storage = self._client.storage.from_(self._bucket)
        try:
            if self._public:
                return storage.get_public_url(key)
            signed = storage.create_signed_url(key, self._url_ttl_seconds)
            return signed["signedURL"]
        except StorageApiError as exc:
            raise ImageStorageError(f"Failed to build Supabase URL for {key!r}: {exc}") from exc
