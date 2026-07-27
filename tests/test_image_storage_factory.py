import pytest

from app.config import settings
from app.services.image_storage import get_image_storage
from app.services.image_storage.local_storage import LocalImageStorage
from app.services.image_storage.s3_storage import S3ImageStorage
from app.services.image_storage.supabase_storage import SupabaseImageStorage


def test_returns_local_storage_by_default(monkeypatch):
    monkeypatch.setattr(settings, "image_storage_backend", "local")

    storage = get_image_storage()

    assert isinstance(storage, LocalImageStorage)


def test_returns_s3_storage_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "image_storage_backend", "s3")
    monkeypatch.setattr(settings, "aws_s3_bucket", "test-bucket")
    monkeypatch.setattr(settings, "aws_region", "us-east-1")

    storage = get_image_storage()

    assert isinstance(storage, S3ImageStorage)


def test_returns_supabase_storage_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "image_storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "service-key")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "cards")

    storage = get_image_storage()

    assert isinstance(storage, SupabaseImageStorage)


def test_raises_on_unknown_backend(monkeypatch):
    monkeypatch.setattr(settings, "image_storage_backend", "azure")

    with pytest.raises(RuntimeError, match="Unknown IMAGE_STORAGE_BACKEND"):
        get_image_storage()
