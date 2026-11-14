"""Google Drive builds the same folder model as the R2 keys, out of real nested folders."""

from app.services.google_drive_service import GoogleDriveStorage
from app.services.storage_service import FOLDER_MIME_TYPE, StorageNotFoundError

import pytest


class _FakeDrive(GoogleDriveStorage):
    """GoogleDriveStorage with the network replaced by an in-memory folder tree."""

    def __init__(self):  # no credentials / HTTP client
        self._root_folder_id = "ROOT"
        self.folders: dict[tuple[str, str], str] = {}  # (parent, name) -> id
        self.files: dict[tuple[str, str], str] = {}
        self.created: list[str] = []

    def _find_child(self, parent_id, name, *, folder):
        return (self.folders if folder else self.files).get((parent_id, name))

    def _call(self, fn):  # only folder creation reaches here
        return fn()

    def _execute(self, request):
        return request()

    class _Files:
        def __init__(self, outer):
            self.outer = outer

        def create(self, body, fields, supportsAllDrives):
            def run():
                assert body["mimeType"] == FOLDER_MIME_TYPE
                new_id = f"F{len(self.outer.folders) + 1}"
                self.outer.folders[(body["parents"][0], body["name"])] = new_id
                self.outer.created.append(body["name"])
                return {"id": new_id}

            return run

    @property
    def _service(self):
        outer = self

        class _S:
            def files(self_inner):
                return _FakeDrive._Files(outer)

        return _S()


def test_album_folder_is_nested_like_the_r2_key():
    drive = _FakeDrive()
    folder = drive.album_originals_folder("studios/acme-photo-1", "Test Couple", 25)
    assert drive.created == ["studios", "acme-photo-1", "albums", "test-couple_25"]
    assert folder == drive.folders[("F3", "test-couple_25")]


def test_existing_folders_are_reused_not_duplicated():
    drive = _FakeDrive()
    first = drive.tenant_root_folder(1, "studios/acme-photo-1")
    again = drive.tenant_root_folder(1, "studios/acme-photo-1")
    assert first == again
    assert drive.created == ["studios", "acme-photo-1"]


def test_legacy_studio_without_prefix_uses_studios_id():
    drive = _FakeDrive()
    drive.tenant_root_folder(7, None)
    assert drive.created == ["studios", "7"]


def test_owns_object_checks_path_keys_and_accepts_drive_ids():
    drive = _FakeDrive()
    assert drive.owns_object("studios/acme-photo-1/branding/logo-x.png", 1)
    assert not drive.owns_object("studios/acme-photo-1/branding/logo-x.png", 2)
    assert not drive.owns_object("studios/acme-photo-1/../other-2/x", 1)
    assert drive.owns_object("1AbCdEfGhIjK", 1)  # opaque Drive id
    assert not drive.owns_object("", 1)


def test_missing_path_key_is_not_found():
    drive = _FakeDrive()
    with pytest.raises(StorageNotFoundError):
        drive._resolve_key("studios/acme-photo-1/branding/logo-x.png")
    assert drive._resolve_key("1AbCdEfGhIjK") == "1AbCdEfGhIjK"


def test_query_values_are_escaped():
    assert GoogleDriveStorage._q("o'brien\\x") == "o\\'brien\\\\x"
