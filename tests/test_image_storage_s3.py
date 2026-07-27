import pytest
from botocore.stub import Stubber

from app.services.exceptions import ImageStorageError
from app.services.image_storage.s3_storage import S3ImageStorage


def _make_storage() -> tuple[S3ImageStorage, Stubber]:
    storage = S3ImageStorage(
        bucket="test-bucket",
        region="us-east-1",
        access_key_id="",
        secret_access_key="",
        url_ttl_seconds=3600,
    )
    stubber = Stubber(storage._client)
    return storage, stubber


def test_put_uploads_object():
    storage, stubber = _make_storage()
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "test-bucket", "Key": "abc.png", "Body": b"data", "ContentType": "image/png"},
    )
    with stubber:
        storage.put("abc.png", b"data", "image/png")


def test_put_raises_image_storage_error_on_failure():
    storage, stubber = _make_storage()
    stubber.add_client_error("put_object", service_error_code="NoSuchBucket")
    with stubber, pytest.raises(ImageStorageError):
        storage.put("abc.png", b"data", "image/png")


def test_delete_removes_object():
    storage, stubber = _make_storage()
    stubber.add_response("delete_object", {}, {"Bucket": "test-bucket", "Key": "abc.png"})
    with stubber:
        storage.delete("abc.png")


def test_url_generates_presigned_url():
    storage = S3ImageStorage(
        bucket="test-bucket",
        region="us-east-1",
        access_key_id="AKIA_TEST",
        secret_access_key="secret",
        url_ttl_seconds=3600,
    )

    url = storage.url("abc.png")

    assert "test-bucket" in url
    assert "abc.png" in url
