"""Shared helpers for the multi-studio test files (kept out of conftest on purpose)."""

import uuid

from app.models.admin import Admin
from app.models.album import Album
from app.models.client import Client
from app.models.media import Media
from app.models.studio import Studio
from app.security.password import hash_password

JPEG = b"\xff\xd8\xff\xe0" + b"0123456789" * 50  # valid JPEG signature, 514 bytes
PASSWORD = "Correct-Horse-123"


def fresh(db, model, pk):
    """Re-read a row from the database, bypassing the session identity map."""
    db.expire_all()
    return db.get(model, pk)


def make_studio(db, name="Studio", quota=10_000_000_000, status="active", used=0, reserved=0) -> Studio:
    studio = Studio(name=name, status=status, quota_bytes=quota, used_bytes=used, reserved_bytes=reserved)
    db.add(studio)
    db.commit()
    db.refresh(studio)
    return studio


def make_admin(db, studio, email, role="studio_admin", password=PASSWORD) -> Admin:
    admin = Admin(
        name=email.split("@")[0],
        email=email,
        password_hash=hash_password(password),
        status="active",
        role=role,
        studio_id=None if role == "super_admin" else studio.id,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def make_super_admin(db, email="root@platform.dev") -> Admin:
    return make_admin(db, None, email, role="super_admin")


def make_client_album(db, studio, name="Client", folder="folder") -> tuple[Client, Album]:
    tag = uuid.uuid4().hex[:8]
    client = Client(
        studio_id=studio.id,
        client_uuid=str(uuid.uuid4()),
        client_name=f"{name}-{tag}",
        password_hash=hash_password("client-pass-1"),
        status="active",
        drive_folder_id=f"{folder}-c-{tag}",
    )
    db.add(client)
    db.commit()
    album = Album(
        studio_id=studio.id,
        client_id=client.id,
        album_uuid=str(uuid.uuid4()),
        album_name=f"Album-{tag}",
        status="active",
        drive_folder_id=f"{folder}-a-{tag}",
    )
    db.add(album)
    db.commit()
    db.refresh(client)
    db.refresh(album)
    return client, album


def make_media(db, studio, client, album, size=1000, name="p.jpg") -> Media:
    media = Media(
        studio_id=studio.id,
        client_id=client.id,
        album_id=album.id,
        file_uuid=str(uuid.uuid4()),
        file_name=name,
        file_type="photo",
        mime_type="image/jpeg",
        file_size=size,
        google_drive_file_id=f"drv-{uuid.uuid4().hex[:10]}",
        status="ready",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


def login(test_client, email, password=PASSWORD):
    return test_client.post("/api/auth/admin/login", json={"email": email, "password": password})


def start_upload(test_client, album_id, upload_id, size, filename="p.jpg"):
    return test_client.post(
        "/api/admin/media/upload-session",
        json={"album_id": album_id, "upload_id": upload_id, "filename": filename, "file_size": size},
    )


def put_to_storage(fake_storage, parent, content, upload_id, filename="p.jpg"):
    """Simulates the browser's direct PUT: the object now exists in storage."""
    file_id = f"drv-{uuid.uuid4().hex[:12]}"
    fake_storage.files[file_id] = {
        "name": filename,
        "mime_type": "image/jpeg",
        "parent_folder_id": parent,
        "content": content,
        "upload_id": upload_id,
    }
    return file_id


def complete_upload(test_client, upload_id, file_id, size):
    return test_client.post(
        "/api/admin/media/upload-complete",
        json={
            "upload_id": upload_id,
            "drive_file_id": file_id,
            "reported_size": size,
            "reported_mime_type": "image/jpeg",
        },
    )


def upload_file(test_client, fake_storage, album, upload_id, content=JPEG, declared=None):
    """Full happy-path upload; returns (start_response, complete_response|None, file_id|None)."""
    declared = len(content) if declared is None else declared
    started = start_upload(test_client, album.id, upload_id, declared)
    if started.status_code != 200:
        return started, None, None
    file_id = put_to_storage(fake_storage, album.drive_folder_id, content, upload_id)
    return started, complete_upload(test_client, upload_id, file_id, len(content)), file_id
