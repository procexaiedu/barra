"""URLs assinadas MinIO para midia."""

from datetime import timedelta

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]

from barra.settings import Settings


def criar_minio(settings: Settings) -> Minio | None:
    if not settings.minio_access_key or not settings.minio_secret_key:
        return None
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_use_ssl,
    )


def presigned_put(client: Minio | None, bucket: str, object_key: str, expires: int = 900) -> str:
    if client is None:
        return f"minio://{bucket}/{object_key}?expires={expires}"
    return client.presigned_put_object(bucket, object_key, expires=timedelta(seconds=expires))


def presigned_get(client: Minio | None, bucket: str, object_key: str, expires: int = 900) -> str:
    if client is None:
        return f"minio://{bucket}/{object_key}?expires={expires}"
    return client.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires))
