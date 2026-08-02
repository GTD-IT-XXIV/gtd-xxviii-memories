"""S3-compatible client for uploading to a Cloudflare R2 bucket.

Used only by the multi-machine batch scan (app/scanning/batch_pipeline.py, driven by
scripts/run_batch_scan_cli.py). The local single-machine pipeline
(app/scanning/pipeline.py) keeps saving thumbnails/originals to local disk via
app/scanning/thumbnails.py and FileResponse - completely unaffected by this module.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class R2Object:
    key: str
    size: int
    last_modified: float  # epoch seconds, for resumability comparisons against Photo.mtime


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def r2_config_from_settings(settings: "Settings") -> R2Config:
    """Builds an R2Config from app.config.Settings, raising a clear error naming
    exactly which env var(s) are missing rather than a cryptic boto3 auth failure."""
    required = {
        "R2_ACCOUNT_ID": settings.r2_account_id,
        "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
        "R2_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
        "R2_BUCKET_NAME": settings.r2_bucket_name,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing R2 setting(s) required for the batch scan: "
            + ", ".join(missing)
            + ". Set them in backend/.env or the environment (see backend/.env.example)."
        )
    return R2Config(
        account_id=settings.r2_account_id,  # type: ignore[arg-type]
        access_key_id=settings.r2_access_key_id,  # type: ignore[arg-type]
        secret_access_key=settings.r2_secret_access_key,  # type: ignore[arg-type]
        bucket_name=settings.r2_bucket_name,  # type: ignore[arg-type]
    )


def guess_content_type(filename: str) -> str:
    ctype, _ = mimetypes.guess_type(filename)
    return ctype or "application/octet-stream"


class R2Client:
    """Thin wrapper around a boto3 S3 client pointed at a Cloudflare R2 bucket."""

    def __init__(self, config: R2Config, max_pool_connections: int = 10) -> None:
        """`max_pool_connections` must be >= the number of threads sharing this client,
        otherwise botocore queues requests behind its connection pool (default 10) and
        silently caps concurrency. Callers that stay single-threaded can leave it."""
        self._bucket = config.bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                max_pool_connections=max_pool_connections,
            ),
            region_name="auto",
        )

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def upload_fileobj(self, key: str, fileobj: BinaryIO, content_type: str | None = None) -> None:
        """Streaming counterpart of upload_bytes: hands botocore an open file handle so
        the payload is chunked off disk instead of read fully into memory first. Used by
        the bulk originals upload, where full-resolution photos are multi-MB and many
        uploads are in flight at once. Thumbnails stay on upload_bytes - they're already
        in memory as freshly encoded JPEG bytes."""
        extra = {"ContentType": content_type} if content_type else {}
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=fileobj, **extra)

    def delete_objects(self, keys: list[str]) -> list[str]:
        """Batch-deletes objects (S3 DeleteObjects caps at 1000 keys/call, so this
        chunks). Returns the keys that failed to delete (empty list = all succeeded)
        instead of raising, so a caller doing a large bulk cleanup can report failures
        without aborting the whole run partway through."""
        failed: list[str] = []
        for i in range(0, len(keys), 1000):
            chunk = keys[i : i + 1000]
            resp = self._s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
            )
            failed.extend(err["Key"] for err in resp.get("Errors", []))
        return failed

    def download_bytes(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def list_objects(self, prefix: str) -> list[R2Object]:
        """Lists every object under `prefix`, paginating past S3's 1000-key-per-call
        cap. Used by the R2-sourced batch scan to enumerate the raw originals a prior
        upload_originals_to_r2_cli.py run uploaded, in place of walking a local
        filesystem."""
        objects: list[R2Object] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects.append(R2Object(key=obj["Key"], size=obj["Size"], last_modified=obj["LastModified"].timestamp()))
        return objects

    def object_exists(self, key: str) -> bool:
        """Used for resumability: lets a re-run recognize an object it already
        uploaded in a prior (possibly interrupted) run without re-uploading it."""
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
