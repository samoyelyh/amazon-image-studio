from io import BytesIO

from pydantic import SecretStr

from app.core.config import Settings
from app.services.storage_service import S3StorageService


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}
        self.health_checked = False

    def upload_fileobj(self, body, bucket: str, key: str, ExtraArgs: dict) -> None:
        assert bucket == "test-bucket"
        self.objects[key] = (body.read(), ExtraArgs["ContentType"], ExtraArgs["Metadata"])

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        data, content_type, metadata = self.objects[Key]
        return {
            "ContentLength": len(data),
            "ContentType": content_type,
            "ETag": '"etag-value"',
            "Metadata": metadata,
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(self.objects[Key][0])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop(Key, None)

    def generate_presigned_url(self, operation: str, *, Params: dict, ExpiresIn: int) -> str:
        return f"https://storage.test/{Params['Key']}?expires={ExpiresIn}"

    def head_bucket(self, *, Bucket: str) -> None:
        self.health_checked = True


def create_service() -> tuple[S3StorageService, FakeS3Client]:
    settings = Settings(
        _env_file=None,
        s3_bucket="test-bucket",
        s3_access_key=SecretStr("access"),
        s3_secret_key=SecretStr("secret"),
        s3_presigned_url_ttl_seconds=60,
    )
    client = FakeS3Client()
    return S3StorageService(settings, client=client), client  # type: ignore[arg-type]


def test_storage_lifecycle() -> None:
    service, client = create_service()
    metadata = service.upload("assets/test.png", b"image-bytes", content_type="image/png", metadata={"owner": "test"})

    assert metadata.size == 11
    assert metadata.content_type == "image/png"
    assert metadata.etag == "etag-value"
    assert service.exists("assets/test.png") is True
    assert service.download("assets/test.png") == b"image-bytes"
    assert service.create_presigned_url("assets/test.png") == "https://storage.test/assets/test.png?expires=60"

    service.check_health()
    assert client.health_checked is True
    service.delete("assets/test.png")
    assert "assets/test.png" not in client.objects
