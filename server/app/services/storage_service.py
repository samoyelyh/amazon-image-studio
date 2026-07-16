from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import BinaryIO

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class StorageObjectMetadata:
    key: str
    size: int
    content_type: str | None
    etag: str | None
    metadata: dict[str, str]


class StorageService(ABC):
    @abstractmethod
    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StorageObjectMetadata:
        raise NotImplementedError

    @abstractmethod
    def download(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def create_presigned_url(self, key: str, *, expires_in: int | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self, key: str) -> StorageObjectMetadata:
        raise NotImplementedError

    @abstractmethod
    def check_health(self) -> None:
        raise NotImplementedError


class S3StorageService(StorageService):
    def __init__(self, settings: Settings, client: BaseClient | None = None) -> None:
        self.settings = settings
        self.bucket = settings.s3_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            use_ssl=settings.s3_secure,
        )

    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StorageObjectMetadata:
        body = BytesIO(data) if isinstance(data, bytes) else data
        self.client.upload_fileobj(
            body,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": metadata or {}},
        )
        return self.get_metadata(key)

    def download(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise

    def create_presigned_url(self, key: str, *, expires_in: int | None = None) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in or self.settings.s3_presigned_url_ttl_seconds,
        )

    def get_metadata(self, key: str) -> StorageObjectMetadata:
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        return StorageObjectMetadata(
            key=key,
            size=int(response.get("ContentLength", 0)),
            content_type=response.get("ContentType"),
            etag=str(response.get("ETag", "")).strip('"') or None,
            metadata=dict(response.get("Metadata", {})),
        )

    def check_health(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)


@lru_cache
def get_storage_service() -> StorageService:
    return S3StorageService(get_settings())
