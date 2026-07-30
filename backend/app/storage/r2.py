"""S3-compatible client for uploading to a Cloudflare R2 bucket.

Used only by the multi-machine batch scan (app/scanning/batch_pipeline.py, driven by
scripts/run_batch_scan_cli.py). The local single-machine pipeline
(app/scanning/pipeline.py) keeps saving thumbnails/originals to local disk via
app/scanning/thumbnails.py and FileResponse - completely unaffected by this module.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from app.config import Settings


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

    def __init__(self, config: R2Config) -> None:
        self._bucket = config.bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
            region_name="auto",
        )

    def upload_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

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
