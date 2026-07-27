import uuid
from pathlib import PurePosixPath

from app.config import settings
from app.services.image_storage.base import ImageStorage
from app.services.image_storage.local_storage import LocalImageStorage
from app.services.image_storage.s3_storage import S3ImageStorage
from app.services.image_storage.supabase_storage import SupabaseImageStorage

__all__ = ["ImageStorage", "generate_image_storage_key", "get_image_storage"]


def generate_image_storage_key(image_filename: str | None) -> str:
    extension = PurePosixPath(image_filename).suffix if image_filename else ""
    return f"{uuid.uuid4()}{extension}"


def get_image_storage() -> ImageStorage:
    backend = settings.image_storage_backend
    if backend == "local":
        return LocalImageStorage(settings.image_storage_local_dir)
    if backend == "s3":
        return S3ImageStorage(
            bucket=settings.aws_s3_bucket,
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            url_ttl_seconds=settings.image_storage_url_ttl_seconds,
        )
    if backend == "supabase":
        return SupabaseImageStorage(
            supabase_url=settings.supabase_url,
            service_key=settings.supabase_service_key,
            bucket=settings.supabase_storage_bucket,
            public=settings.supabase_storage_public,
            url_ttl_seconds=settings.image_storage_url_ttl_seconds,
        )
    raise RuntimeError(f"Unknown IMAGE_STORAGE_BACKEND: {backend!r}")
