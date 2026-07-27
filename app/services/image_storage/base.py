from typing import Protocol


class ImageStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store `data` under `key`. Raises ImageStorageError on failure."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object stored under `key`. Must be idempotent: deleting a key that
        doesn't exist is not an error."""
        ...

    def url(self, key: str) -> str:
        """Return a URL a client can use to fetch the object stored under `key`."""
        ...
