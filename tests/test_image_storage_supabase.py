from unittest.mock import MagicMock, patch

import pytest

from app.services.exceptions import ImageStorageError
from app.services.image_storage.supabase_storage import SupabaseImageStorage


def _make_storage(public: bool) -> tuple[SupabaseImageStorage, MagicMock]:
    with patch("app.services.image_storage.supabase_storage.create_client") as create_client:
        fake_client = MagicMock()
        create_client.return_value = fake_client
        storage = SupabaseImageStorage(
            supabase_url="https://example.supabase.co",
            service_key="service-key",
            bucket="cards",
            public=public,
            url_ttl_seconds=3600,
        )
    return storage, fake_client


def test_put_uploads_via_storage_client():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value

    storage.put("abc.png", b"data", "image/png")

    bucket.upload.assert_called_once_with("abc.png", b"data", {"content-type": "image/png"})


def test_put_falls_back_to_update_on_upload_conflict():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value
    bucket.upload.side_effect = Exception("Duplicate")

    storage.put("abc.png", b"data", "image/png")

    bucket.update.assert_called_once_with("abc.png", b"data", {"content-type": "image/png"})


def test_put_raises_image_storage_error_when_update_also_fails():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value
    bucket.upload.side_effect = Exception("Duplicate")
    bucket.update.side_effect = Exception("still failing")

    with pytest.raises(ImageStorageError):
        storage.put("abc.png", b"data", "image/png")


def test_delete_removes_object():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value

    storage.delete("abc.png")

    bucket.remove.assert_called_once_with(["abc.png"])


def test_delete_missing_key_is_a_no_op():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value
    bucket.remove.side_effect = Exception("not found")

    storage.delete("abc.png")


def test_url_returns_public_url_when_public():
    storage, client = _make_storage(public=True)
    bucket = client.storage.from_.return_value
    bucket.get_public_url.return_value = "https://example.supabase.co/public/cards/abc.png"

    url = storage.url("abc.png")

    assert url == "https://example.supabase.co/public/cards/abc.png"
    bucket.get_public_url.assert_called_once_with("abc.png")


def test_url_returns_signed_url_when_not_public():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value
    bucket.create_signed_url.return_value = {"signedURL": "https://example.supabase.co/signed/abc.png"}

    url = storage.url("abc.png")

    assert url == "https://example.supabase.co/signed/abc.png"
    bucket.create_signed_url.assert_called_once_with("abc.png", 3600)


def test_url_raises_image_storage_error_on_failure():
    storage, client = _make_storage(public=False)
    bucket = client.storage.from_.return_value
    bucket.create_signed_url.side_effect = Exception("boom")

    with pytest.raises(ImageStorageError):
        storage.url("abc.png")
