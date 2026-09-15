from app.models.album import Album
from app.models.client import Client
from app.models.download_job import DownloadJob
from app.models.media import Media
from app.models.upload_session import UploadSession
from app.schemas.album import AlbumResponse
from app.schemas.download_job import DownloadJobResponse
from app.schemas.media import (
    MediaResponse,
    UploadSessionListItem,
    UploadStatusResponse,
)


def album_to_response(album: Album, media_count: int = 0) -> AlbumResponse:
    return AlbumResponse(
        id=album.id,
        album_uuid=album.album_uuid,
        client_id=album.client_id,
        album_name=album.album_name,
        description=album.description,
        status=album.status,
        expires_at=album.expires_at,
        created_at=album.created_at,
        media_count=media_count,
    )


def media_to_response(media: Media) -> MediaResponse:
    return MediaResponse(
        id=media.id,
        file_uuid=media.file_uuid,
        album_id=media.album_id,
        file_name=media.file_name,
        title=media.title,
        description=media.description,
        file_type=media.file_type,
        mime_type=media.mime_type,
        file_size=media.file_size,
        has_thumbnail=bool(media.thumbnail_reference),
        status=media.status,
        created_at=media.created_at,
    )


def download_job_to_response(job: DownloadJob, client: Client | None = None) -> DownloadJobResponse:
    # zip_path is deliberately excluded - internal disk path, never sent
    # to a client, same as never sending a Google Drive file id.
    # has_password reflects whether the owning client has a download password set.
    return DownloadJobResponse(
        id=job.id,
        status=job.status,
        total_files=job.total_files,
        completed_files=job.completed_files,
        total_bytes=job.total_bytes,
        completed_bytes=job.completed_bytes,
        error_message=job.error_message,
        has_password=bool(client and client.download_password_hash) if client else False,
        created_at=job.created_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
    )


def upload_session_to_response(session: UploadSession) -> UploadStatusResponse:
    percentage = 0
    if session.total_bytes:
        # Never report 100% before the session has actually completed
        # (Section 8), even if bytes_uploaded briefly equals total_bytes
        # mid-transfer (e.g. right before the final finalize response).
        raw = int((session.bytes_uploaded / session.total_bytes) * 100)
        percentage = min(raw, 99) if session.status != "completed" else 100
    return UploadStatusResponse(
        upload_id=session.upload_id,
        status=session.status,
        total_bytes=session.total_bytes,
        bytes_uploaded=session.bytes_uploaded,
        percentage=percentage,
        media_id=session.media_id,
        error_code=session.error_code,
        error_message=session.error_message,
    )


def upload_session_list_item(
    session: UploadSession, album_name: str, client_name: str
) -> UploadSessionListItem:
    """
    Enrichment of upload_session_to_response for the "recent uploads" list
    the Uploads page restores after a refresh: adds the filename plus the
    owning album/client label so the UI can render the row even though the
    original in-memory File object is gone.
    """
    percentage = 0
    if session.total_bytes:
        raw = int((session.bytes_uploaded / session.total_bytes) * 100)
        percentage = min(raw, 99) if session.status != "completed" else 100
    return UploadSessionListItem(
        upload_id=session.upload_id,
        filename=session.filename,
        album_id=session.album_id,
        album_name=album_name,
        client_name=client_name,
        status=session.status,
        total_bytes=session.total_bytes,
        bytes_uploaded=session.bytes_uploaded,
        percentage=percentage,
        media_id=session.media_id,
        error_code=session.error_code,
        error_message=session.error_message,
        created_at=session.created_at,
    )
