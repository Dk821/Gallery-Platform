# File storage structure (Google Drive or Cloudflare R2)

> **v0.5 (31/10/2026):** the default backend is **Google Drive** (`STORAGE_PROVIDER=google_drive`). It uses
> the same layout as the R2 keys below, built from real nested Drive folders under
> `GOOGLE_DRIVE_ROOT_FOLDER_ID`: `studios/{studio-name}-{id}/albums/{client}_{albumId}/{file}`, with logos in
> `studios/{studio}/branding/`. Folders are found-or-created level by level; the database stores the Drive
> folder/file ids. Everything below describes the layout; read "object key" as "folder path" on Drive.
> `STORAGE_PROVIDER=r2` keeps the original bucket behaviour.

All files live in ONE R2 bucket (`R2_BUCKET`). Every object key starts with the
studio's own folder, `studios/{studio-name}-{studio_id}/`, so each studio's files
are isolated under a readable prefix. The browser never sees the bucket
directly: photos and videos are viewed/downloaded through the backend, which
checks the logged-in studio.

## Layout

```
<bucket>/
└── studios/
    ├── acme-photo-1/                                  ← Studio A  (name "Acme Photo", studio id 1)
    │   ├── branding/
    │   │   └── logo-<version>.png                     ← Studio A brand logo
    │   ├── albums/
    │   │   ├── test-couple_25/                        ← originals of album id 25 (client "Test Couple")
    │   │   │   ├── <media-uuid>                       ← original photo / video file
    │   │   │   └── <media-uuid>
    │   │   └── test-couple_26/                        ← originals of album id 26 (same client)
    │   │       └── <media-uuid>
    │   └── Test Couple_C_<uid>/                       ← one folder per client
    │       └── Thumbnails/
    │           ├── <hex>-thumb_<uuid>.webp            ← photo thumbnail / video poster
    │           └── <hex>-thumb_<uuid>.webp
    │
    └── beta-weddings-2/                               ← Studio B  (name "Beta Weddings", studio id 2)
        ├── branding/
        │   └── logo-<version>.png
        ├── albums/
        │   └── sam-and-lee_31/
        │       └── <media-uuid>
        └── Sam and Lee_C_<uid>/
            └── Thumbnails/
                └── <hex>-thumb_<uuid>.webp
```

## Where things are stored

| What | Path pattern | Example (Studio A) |
|---|---|---|
| Studio brand logo | `studios/{studio}/branding/logo-{version}.png` | `studios/acme-photo-1/branding/logo-9f3a1c2b7d4e8a60.png` |
| Client image / video (original) | `studios/{studio}/albums/{client-name}_{album_id}/{media_uuid}` | `studios/acme-photo-1/albums/test-couple_25/26c9885b-828c-4c4b-9df5-e0b64df202fb` |
| Client image thumbnail / video poster | `studios/{studio}/{client folder}/Thumbnails/{hex}-thumb_{uuid}.webp` | `studios/acme-photo-1/Test Couple_C_FE2C06FBE08A/Thumbnails/6325…-thumb_b88f….webp` |

## Naming rules

- `{studio}` = `{studio-name}-{studio_id}`: the studio's name turned into lower-case
  letters, digits and hyphens (at most 30 characters; `studio` if the name has no
  usable letters, e.g. non-Latin script), then `-` and the numeric id. The id keeps
  the folder unique and lets the server recognise a studio's objects, so two studios
  with the same name never share a folder.
- **Chosen once, never changed.** The folder name is saved on the studio
  (`studios.storage_prefix`) when the studio is created. Renaming the studio later
  does NOT move any file (R2 cannot rename a folder; it would have to copy every
  file). The same applies to clients and albums: their folder names are fixed at
  creation and only the database shows the new name.
- `{client-name}_{album_id}` (albums folder): the client's name at the time the album
  was created, in the same letters-digits-hyphens form, then `_` and the album id.
  Every album has its own folder, so deleting an album removes its originals with it.
- `{client folder}` = `{Client Name}_C_{uid}`: readable client name plus a random id
  fixed at creation (spaces are kept).
- `{version}` in the logo name: first 16 characters of the SHA-256 of the processed
  image. A new logo gets a new name, so browsers never show a stale one. Logos are
  always re-encoded to a 512 px PNG (metadata removed).
- `{media_uuid}`: random id chosen by the server when the upload starts. The original
  file name is kept in the database, not in the storage key.
- Thumbnails belong to the client (not to an album), so they stay in place when a
  photo is moved to another album.

## Studios created before this layout

A studio created before readable folders existed has no saved folder name and keeps
the plain form, so none of its files move:

```
studios/1/branding/logo-<version>.png
studios/1/albums/25/<media-uuid>
studios/1/<ClientName>_C_<uid>/Thumbnails/<hex>-thumb_<uuid>.webp
```

Every studio created from now on (in the Super Admin console or with
`app.legacy_to_studio --create-studio`) gets the readable form. The server accepts
both forms: a key belongs to a studio when the last `-`-separated part of its
folder is that studio's id.

## Related notes

- Deleting a photo removes its original and its thumbnail from R2.
- Deleting an album removes everything under its folder (its originals) and frees
  the quota; deleting a client removes the client folder, including its thumbnails.
  (For the plain-id form above, an album's originals are removed one by one when the
  photos are deleted.)
- ZIP downloads are built as a temporary file on the server and are not kept in R2.
- Studio quota counts original files only (not thumbnails or the logo).
- The bucket needs a CORS rule allowing `PUT` from the site address, because the
  browser uploads originals straight to R2 with a short-lived signed URL.
- Where this is implemented: `app/services/storage_paths.py` (names),
  `app/services/r2_storage.py` (keys and tenant check), `studio_service.py`
  (saves the folder when a studio is created).
