import time
import uuid
from typing import BinaryIO, Iterator

from app.services.storage_service import (
    StorageError,
    StorageNotFoundError,
    StorageService,
    StorageTimeoutError,
    StoredFile,
)


class FakeStorageService(StorageService):
    """
    Records folders/files in memory instead of calling Google Drive.
    Lets tests assert on what would have been sent to Drive (e.g. "was
    create_folder called with the right parent?") without any network
    dependency, per spec Section 44.
    """

    def __init__(self):
        self.folders: dict[str, dict] = {}
        self.files: dict[str, dict] = {}
        self.deleted_folder_ids: list[str] = []
        self.deleted_file_ids: list[str] = []
        self.fail_next_upload = False
        self.fail_next_create_folder = False
        self.fail_next_move = False
        self.fail_next_rename = False
        # Upload-hardening test hooks (see tests/test_upload_hardening.py).
        self.fail_next_upload_timeout = False
        self.upload_delay_seconds = 0.0
        self.uploads_in_flight = 0
        self.max_uploads_in_flight_seen = 0

    def create_folder(self, name: str, parent_folder_id: str | None = None) -> str:
        if self.fail_next_create_folder:
            self.fail_next_create_folder = False
            from app.services.storage_service import StorageError

            raise StorageError("simulated create_folder failure")
        folder_id = f"folder-{uuid.uuid4().hex[:12]}"
        self.folders[folder_id] = {"name": name, "parent_folder_id": parent_folder_id}
        return folder_id

    def delete_folder(self, folder_id: str) -> None:
        self.folders.pop(folder_id, None)
        self.deleted_folder_ids.append(folder_id)

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        if self.fail_next_rename:
            self.fail_next_rename = False
            from app.services.storage_service import StorageError

            raise StorageError("simulated rename_folder failure")
        # A folder can legitimately exist in Drive without being tracked
        # here (e.g. rows seeded straight into the DB in tests, or - in
        # real life - folders provisioned before this fake existed).
        # Renaming is a metadata-only operation on an existing folder id,
        # so just upsert rather than requiring prior create_folder().
        record = self.folders.setdefault(folder_id, {"name": None, "parent_folder_id": None})
        record["name"] = new_name

    def upload(
        self,
        file_obj: BinaryIO,
        filename: str,
        mime_type: str,
        parent_folder_id: str,
        *,
        progress_callback=None,
        upload_id: str | None = None,
    ) -> StoredFile:
        if self.fail_next_upload:
            self.fail_next_upload = False
            raise StorageError("simulated upload failure")
        if self.fail_next_upload_timeout:
            self.fail_next_upload_timeout = False
            raise StorageTimeoutError("simulated upload timeout")

        self.uploads_in_flight += 1
        self.max_uploads_in_flight_seen = max(self.max_uploads_in_flight_seen, self.uploads_in_flight)
        try:
            if self.upload_delay_seconds:
                time.sleep(self.upload_delay_seconds)

            content = file_obj.read()
            total = len(content)
            if progress_callback:
                # Simulate a couple of chunks so callers exercising
                # progress reporting see more than one call.
                half = total // 2
                if half:
                    progress_callback(half, total)
                progress_callback(total, total)

            file_id = f"file-{uuid.uuid4().hex[:12]}"
            self.files[file_id] = {
                "name": filename,
                "mime_type": mime_type,
                "parent_folder_id": parent_folder_id,
                "content": content,
                "upload_id": upload_id,
            }
            return StoredFile(provider_file_id=file_id, name=filename, size=total, mime_type=mime_type)
        finally:
            self.uploads_in_flight -= 1

    def download(
        self,
        provider_file_id: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> Iterator[bytes]:
        record = self.files.get(provider_file_id)
        if record is None:
            raise StorageNotFoundError(provider_file_id)
        content = record["content"]
        if range_start is not None or range_end is not None:
            start = range_start if range_start is not None else 0
            end = range_end + 1 if range_end is not None else len(content)
            content = content[start:end]
        yield content

    def delete(self, provider_file_id: str) -> None:
        self.files.pop(provider_file_id, None)
        self.deleted_file_ids.append(provider_file_id)

    def get_file(self, provider_file_id: str) -> StoredFile:
        record = self.files.get(provider_file_id)
        if record is None:
            raise StorageNotFoundError(provider_file_id)
        return StoredFile(
            provider_file_id=provider_file_id,
            name=record["name"],
            size=len(record["content"]),
            mime_type=record["mime_type"],
        )

    def move_file(
        self,
        provider_file_id: str,
        new_parent_folder_id: str,
        old_parent_folder_id: str | None = None,
    ) -> None:
        if self.fail_next_move:
            self.fail_next_move = False
            from app.services.storage_service import StorageError

            raise StorageError("simulated move failure")
        record = self.files.get(provider_file_id)
        if record is None:
            raise StorageNotFoundError(provider_file_id)
        record["parent_folder_id"] = new_parent_folder_id

    def get_metadata(self) -> dict:
        total = sum(len(f["content"]) for f in self.files.values())
        return {"available": True, "usage_bytes": total, "limit_bytes": None}

    def create_resumable_session(
        self,
        filename: str,
        mime_type: str,
        file_size: int,
        parent_folder_id: str,
        *,
        upload_id: str | None = None,
        origin: str | None = None,
    ) -> str:
        # The bytes never pass through this server in the direct-upload
        # architecture - the fake only has to mint a session URL, mirroring
        # what real Drive returns. start_direct_upload stores it on the
        # UploadSession row, so tests can assert it flowed through.
        return f"https://fake.drive/resumable/{uuid.uuid4().hex}"
