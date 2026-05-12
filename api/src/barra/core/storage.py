"""URLs assinadas MinIO para midia."""

from datetime import timedelta

try:
    from minio import Minio
    from minio.error import S3Error
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]
    S3Error = Exception  # type: ignore[misc,assignment]

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


def ensure_bucket(client: Minio | None, bucket: str) -> None:
    """Garante que o bucket existe. Idempotente sob corrida entre réplicas."""
    if client is None:
        return
    if client.bucket_exists(bucket):
        return
    try:
        client.make_bucket(bucket)
    except S3Error as exc:
        # BucketAlreadyOwnedByYou em corrida entre réplicas: ok, outra réplica criou.
        if getattr(exc, "code", "") != "BucketAlreadyOwnedByYou":
            raise


def presigned_put(client: Minio | None, bucket: str, object_key: str, expires: int = 900) -> str:
    if client is None:
        return f"minio://{bucket}/{object_key}?expires={expires}"
    return client.presigned_put_object(bucket, object_key, expires=timedelta(seconds=expires))


def presigned_get(client: Minio | None, bucket: str, object_key: str, expires: int = 900) -> str:
    if client is None:
        return f"minio://{bucket}/{object_key}?expires={expires}"
    return client.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires))


def remove_object(client: Minio | None, bucket: str, object_key: str) -> None:
    """Remove objeto do bucket. Silencioso quando objeto já não existe (S3 semantics)."""
    if client is None:
        return
    try:
        client.remove_object(bucket, object_key)
    except S3Error as exc:
        if getattr(exc, "code", "") != "NoSuchKey":
            raise
