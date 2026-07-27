from pathlib import Path

from app.services.exceptions import ImageStorageError


class LocalImageStorage:
    def __init__(self, base_dir: str):
        self._base_dir = Path(base_dir)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            (self._base_dir / key).write_bytes(data)
        except OSError as exc:
            raise ImageStorageError(f"Failed to write local image {key!r}: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            (self._base_dir / key).unlink(missing_ok=True)
        except OSError as exc:
            raise ImageStorageError(f"Failed to delete local image {key!r}: {exc}") from exc

    def url(self, key: str) -> str:
        raise NotImplementedError(
            "LocalImageStorage URLs are served via /cards/{id}/image, keyed by record id, "
            "not by storage key -- see build_image_url()."
        )
