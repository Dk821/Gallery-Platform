"""
StorageService is the single seam between the application and whatever
actually holds the media files. Per spec Section 3: no route, service, or
model outside this module and its concrete implementations may import a
storage provider's SDK directly. Swapping Google Drive for R2/S3/B2 later
means writing one new class here - nothing else changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterator

# Called after each chunk is confirmed by the provider, as
# (bytes_uploaded, total_bytes). Implementations must never report
# bytes_uploaded >= total_bytes until the upload has actually finished.
ProgressCallback = Callable[[int, int], None]


@dataclass
class StoredFile:
    """What we get back after a successful upload or a metadata lookup."""

    provider_file_id: str
    name: str
    size: int
    mime_type: str


class StorageError(Exception):
    """Base class for all storage-layer failures the rest of the app should handle."""


class StorageNotFoundError(StorageError):
    """The requested file or folder does not exist (or was deleted) at the provider."""


class StorageQuotaExceededError(StorageError):
    """The storage provider rejected the operation due to quota/rate limits."""


class StorageTimeoutError(StorageError):
    """A chunk or the overall upload session exceeded its configured timeout."""


class StorageService(ABC):
    @abstractmethod
    def create_folder(self, name: str, parent_folder_id: str | None = None) -> str:
        """Creates a folder and returns its provider-specific folder id."""

    @abstractmethod
    def delete_folder(self, folder_id: str) -> None:
        """
        Deletes a folder and everything inside it. Implementations should
        prefer moving to trash over a permanent delete where the provider
        distinguishes the two - see google_drive_service.py's delete() for
        why (the service account frequently doesn't own the folder tree it
        was shared into, and only the owner/an organizer can permanently
        delete there).
        """

    @abstractmethod
    def rename_folder(self, folder_id: str, new_name: str) -> None:
        """
        Renames a folder in place - a metadata-only operation, never a
        delete+recreate. The folder id (and everything inside it) is
        untouched; only its display name changes. Used when a client/album
        is renamed so the Drive folder's readable name stays in sync while
        its stable id suffix never changes.
        """

    @abstractmethod
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
        """
        Uploads a file-like object. Implementations must stream this rather
        than reading it fully into memory (Section 38) - the caller may be
        handing over a multi-GB video.

        progress_callback, if given, is invoked after each chunk with real
        bytes-transferred-to-the-provider counts (not just bytes read
        locally). upload_id, if given, is used for structured logging and
        (where the provider supports it) tagging the created file so it can
        later be identified as application-managed for orphan reconciliation.
        """

    @abstractmethod
    def download(
        self,
        provider_file_id: str,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> Iterator[bytes]:
        """
        Returns a chunked iterator over the file's bytes - never the whole
        file at once.

        range_start/range_end, if given, are inclusive byte offsets (HTTP
        Range semantics) and request only that slice of the file from the
        provider instead of the whole thing. Both None means "the whole
        file", matching prior behavior. Implementations that can't do a
        partial fetch should raise StorageError rather than silently
        ignoring the range.
        """

    @abstractmethod
    def delete(self, provider_file_id: str) -> None:
        """
        Deletes a single file. Must be a no-op (not an error) if already
        gone. Prefer trash over permanent delete where the provider
        distinguishes the two - see google_drive_service.py's delete().
        """

    @abstractmethod
    def get_file(self, provider_file_id: str) -> StoredFile:
        """Fetches metadata for a single file."""

    @abstractmethod
    def move_file(
        self,
        provider_file_id: str,
        new_parent_folder_id: str,
        old_parent_folder_id: str | None = None,
    ) -> None:
        """
        Moves a file to a new parent folder WITHOUT re-uploading its
        content - this is a metadata operation at the provider (Drive
        supports it via addParents/removeParents on files.update), not a
        download+reupload. Used when an admin reassigns a media item to a
        different album.
        """

    @abstractmethod
    def get_metadata(self) -> dict:
        """
        Provider-level metadata - e.g. storage quota used/total, if the
        provider's API exposes it. Section 42: if exact numbers aren't
        available for the configured account, return a dict with
        `available: False` rather than inventing numbers.
        """
