"""
Cloudflare R2 (S3-compatible) implementation of StorageService.

Status: the only storage backend (Google Drive is no longer selectable). This
class implements the full StorageService contract, is unit-tested against a
fake S3 client, and has
NOT been exercised against a live R2 bucket in this repository's test run -
smoke-test it in a staging bucket before production (docs/MULTI_STUDIO.md).

Design notes
  * Credentials come ONLY from environment variables (R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET). They are never
    returned by an API, logged, or sent to the browser. The browser only ever
    receives a short-lived presigned URL for ONE object key, scoped to one
    upload (R2_PRESIGN_TTL_SECONDS).
  * Object keys are tenant-scoped and readable:
    ``studios/{studio-name}-{studio_id}/albums/{client-name}_{album_id}/{media_uuid}``
    (the last segment is the media's unguessable file UUID because the numeric
    media id does not exist until the upload completes). Studios created before
    named folders use ``studios/{studio_id}/albums/{album_id}/{media_uuid}``.
    owns_object() refuses any key outside the calling studio's folder, so one
    studio can never claim, read or delete another studio's object.
    See app.services.storage_paths and STORAGE_STRUCTURE.md.
  * R2 enforces NO per-studio quota - the platform does, in
    app.services.quota_service, before a presigned URL is ever issued.
  * "Folders" are just key prefixes; there is nothing to create. rename_folder
    and move_file are intentional no-ops: keys stay stable and album/client
    membership lives in the database, so renaming/moving never has to copy
    (and re-price) object data.
  * A single presigned PUT is limited to 5 GiB by S3 semantics; larger files
    need multipart upload (follow-up, see docs).
"""

import logging
import uuid
from typing import BinaryIO, Iterator

from app.config.settings import Settings
from app.services.storage_service import (
    ProgressCallback,
    StorageError,
    StorageNotFoundError,
    StorageService,
    StoredFile,
)

logger = logging.getLogger("gallery.storage.r2")

MAX_SINGLE_PUT_BYTES = 5 * 1024**3
_READ_CHUNK = 1024 * 1024


def tenant_prefix(studio_id: int) -> str:
    """The folder of a studio that has no stored named prefix (legacy form)."""
    return f"studios/{studio_id}/"


class R2Storage(StorageService):
    provider_name = "r2"
    uses_named_layout = True

    def __init__(self, settings: Settings, client=None):
        self._bucket = settings.r2_bucket
        self._presign_ttl = settings.r2_presign_ttl_seconds
        if client is not None:  # injected (tests)
            self._s3 = client
            return
        missing = [
            name
            for name, value in (
                ("R2_ACCOUNT_ID", settings.r2_account_id),
                ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
                ("R2_BUCKET", settings.r2_bucket),
            )
            if not value
        ]
        if missing:
            # Names only - never values.
            raise StorageError(f"R2 storage settings are missing: {', '.join(missing)}")
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - depends on deployment
            raise StorageError("boto3 is required for R2 storage (pip install boto3).") from exc
        endpoint = settings.r2_endpoint_url or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
        )

    # ------------------------------------------------------------- tenancy
    def object_key_for(
        self,
        studio_id: int,
        album_id: int,
        media_uuid: str,
        *,
        studio_prefix: str | None = None,
        album_folder: str | None = None,
    ) -> str | None:
        if studio_prefix and album_folder:
            return f"{album_folder.rstrip('/')}/{media_uuid}"
        root = (studio_prefix or tenant_prefix(studio_id)).rstrip("/")
        return f"{root}/albums/{album_id}/{media_uuid}"

    def tenant_root_folder(self, studio_id: int, studio_prefix: str | None = None) -> str | None:
        return (studio_prefix or tenant_prefix(studio_id)).rstrip("/")

    def album_originals_folder(self, studio_prefix: str, client_name: str, album_id: int) -> str | None:
        from app.services.storage_paths import slugify

        return f"{studio_prefix.rstrip('/')}/albums/{slugify(client_name, 'client')}_{album_id}"

    def owns_object(self, object_id: str, studio_id: int) -> bool:
        if not object_id or ".." in object_id or object_id.startswith("/"):
            return False
        # "studios/<folder>/...": the folder is either the bare id (legacy) or
        # "<name>-<id>"; the id is always the last dash-separated part, so a
        # studio can never match another studio's folder.
        parts = object_id.split("/")
        if len(parts) < 3 or parts[0] != "studios":
            return False
        return parts[1].rsplit("-", 1)[-1] == str(studio_id)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", None) or {}
        code = str((response.get("Error") or {}).get("Code", ""))
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return code in ("404", "NoSuchKey", "NotFound") or status == 404

    def _wrap(self, exc: Exception, what: str) -> StorageError:
        if self._is_not_found(exc):
            return StorageNotFoundError(what)
        # Message only carries the operation, never request headers/credentials.
        # The log line adds R2's own error code (e.g. AccessDenied, NoSuchBucket,
        # InvalidAccessKeyId) so a failing setup can be diagnosed from the server log.
        response = getattr(exc, "response", None) or {}
        err = response.get("Error") or {}
        logger.warning(
            "R2 %s failed: %s code=%s status=%s message=%s",
            what,
            type(exc).__name__,
            err.get("Code", "-"),
            (response.get("ResponseMetadata") or {}).get("HTTPStatusCode", "-"),
            str(err.get("Message", exc))[:200],
        )
        return StorageError(f"R2 operation failed: {what}")

    # ------------------------------------------------------------- folders
    def create_folder(self, name: str, parent_folder_id: str | None = None) -> str:
        clean = name.strip("/")
        return f"{parent_folder_id.rstrip('/')}/{clean}" if parent_folder_id else clean

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        return None  # prefixes are stable ids; the readable name lives in the database

    def delete_folder(self, folder_id: str) -> None:
        prefix = folder_id.rstrip("/") + "/"
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if keys:
                    self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": keys, "Quiet": True})
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "delete_folder") from exc

    def list_folder_contents(self, folder_id: str) -> list[StoredFile]:
        prefix = folder_id.rstrip("/") + "/"
        out: list[StoredFile] = []
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix, Delimiter="/"):
                for obj in page.get("Contents", []):
                    out.append(
                        StoredFile(
                            provider_file_id=obj["Key"],
                            name=obj["Key"].rsplit("/", 1)[-1],
                            size=int(obj.get("Size", 0)),
                            mime_type="",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "list_folder_contents") from exc
        return out

    def move_file(self, provider_file_id: str, new_parent_folder_id: str, old_parent_folder_id: str | None = None) -> None:
        return None  # keys are stable; album membership is a database fact

    # --------------------------------------------------------------- upload
    def upload(
        self,
        file_obj: BinaryIO,
        filename: str,
        mime_type: str,
        parent_folder_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        upload_id: str | None = None,
    ) -> StoredFile:
        key = f"{parent_folder_id.rstrip('/')}/{uuid.uuid4().hex}-{filename}"
        try:
            self._s3.upload_fileobj(file_obj, self._bucket, key, ExtraArgs={"ContentType": mime_type})
            head = self._s3.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "upload") from exc
        size = int(head.get("ContentLength", 0))
        if progress_callback:
            progress_callback(size, size)
        return StoredFile(provider_file_id=key, name=filename, size=size, mime_type=mime_type)

    def create_resumable_session(
        self,
        filename: str,
        mime_type: str,
        file_size: int,
        parent_folder_id: str,
        *,
        upload_id: str | None = None,
        origin: str | None = None,
        object_key: str | None = None,
    ) -> str:
        if file_size > MAX_SINGLE_PUT_BYTES:
            raise StorageError("Files over 5 GiB need multipart upload, which is not enabled for R2 yet.")
        key = object_key or f"{parent_folder_id.rstrip('/')}/{upload_id or uuid.uuid4().hex}/{filename}"
        try:
            return self._s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": mime_type,
                    # Signed: R2 rejects a body whose length differs from what
                    # was reserved against the quota.
                    "ContentLength": int(file_size),
                },
                ExpiresIn=self._presign_ttl,
                HttpMethod="PUT",
            )
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "create_resumable_session") from exc

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        if not key or ".." in key or key.startswith("/"):
            raise StorageError("Invalid object key.")
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "put_bytes") from exc

    # ----------------------------------------------------------- read/delete
    def download(
        self, provider_file_id: str, *, range_start: int | None = None, range_end: int | None = None
    ) -> Iterator[bytes]:
        kwargs = {"Bucket": self._bucket, "Key": provider_file_id}
        if range_start is not None or range_end is not None:
            start = range_start if range_start is not None else 0
            kwargs["Range"] = f"bytes={start}-{'' if range_end is None else range_end}"
        try:
            body = self._s3.get_object(**kwargs)["Body"]
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "download") from exc
        try:
            yield from body.iter_chunks(_READ_CHUNK)
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    def delete(self, provider_file_id: str) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=provider_file_id)  # idempotent on S3/R2
        except Exception as exc:  # noqa: BLE001
            if self._is_not_found(exc):
                return
            raise self._wrap(exc, "delete") from exc

    def get_file(self, provider_file_id: str) -> StoredFile:
        try:
            head = self._s3.head_object(Bucket=self._bucket, Key=provider_file_id)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "get_file") from exc
        return StoredFile(
            provider_file_id=provider_file_id,
            name=provider_file_id.rsplit("/", 1)[-1],
            size=int(head.get("ContentLength", 0)),
            mime_type=head.get("ContentType", ""),
        )

    def get_metadata(self) -> dict:
        # R2 exposes no per-account quota API; report that honestly (spec Section 42).
        return {"available": False, "provider": "r2", "reason": "R2 does not expose a storage quota API."}
