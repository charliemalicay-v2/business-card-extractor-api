import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.services.exceptions import ImageStorageError


class S3ImageStorage:
    def __init__(
        self,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        url_ttl_seconds: int,
    ):
        self._bucket = bucket
        self._url_ttl_seconds = url_ttl_seconds
        client_kwargs = {}
        if region:
            client_kwargs["region_name"] = region
        if access_key_id and secret_access_key:
            client_kwargs["aws_access_key_id"] = access_key_id
            client_kwargs["aws_secret_access_key"] = secret_access_key
        self._client = boto3.client("s3", **client_kwargs)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except (ClientError, BotoCoreError) as exc:
            raise ImageStorageError(f"Failed to upload image {key!r} to S3: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise ImageStorageError(f"Failed to delete image {key!r} from S3: {exc}") from exc

    def url(self, key: str) -> str:
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._url_ttl_seconds,
            )
        except (ClientError, BotoCoreError) as exc:
            raise ImageStorageError(f"Failed to build S3 URL for {key!r}: {exc}") from exc
