# Multi-studio platform

LoveStory PH is a multi-tenant platform: **one FastAPI app + one MySQL
database serve many photography studios**, each fully isolated, with all files
in one Cloudflare R2 bucket under a per-studio prefix (`STORAGE_STRUCTURE.md`).
The existing auth, galleries and upload pipeline are extended, not replaced.
This file is the operator/developer reference for tenancy, roles, quotas, the
Super Admin API and console, and migrating an old install.
Read `ARCHITECTURE.md` first for the underlying layering
(routes → services → models → storage).

---

## 1. Roles and tenancy

| Role | Belongs to | Can do |
|---|---|---|
| `super_admin` | no studio (platform) | Manage studios, quotas, studio-admin credentials, platform stats, all audit logs. **Cannot** browse a studio's clients/albums/media (`/api/admin/*` returns `403 STUDIO_ADMIN_REQUIRED`). |
| `studio_admin` | exactly one studio | Manage only their own studio's profile, clients, albums, media, galleries; upload/delete subject to quota and studio status. |
| `client` (gallery visitor) | one client row → one studio | View only the galleries/albums/media that client is authorised for (unchanged contract). |

Rules that hold everywhere:

* The studio is **always derived from the authenticated admin / client row** in
  the database. `studio_id`, `role`, `quota_bytes` or ownership sent in a URL,
  query string or JSON body is ignored (or rejected by the schema).
* Every studio-owned table carries `studio_id` and every service lookup filters
  on it. A resource of another studio answers **404** (not 403), so ids cannot be
  probed (IDOR).
* One auth system: the existing signed `admin_session` cookie (now also carries a
  `session_version`, so resetting/changing a password revokes old cookies) and the
  DB-backed `client_session`.

### Studio status
`active | suspended`. A suspended studio:
* studio admins can still **read** (GET/HEAD/OPTIONS) but every write returns `403 STUDIO_SUSPENDED` (uploads, deletes, profile edits, new clients/albums);
* its **clients cannot log in** and existing client sessions stop working.
Clients whose `studio_id` is still NULL (unmapped legacy rows, see §3) are still allowed so a half-finished migration does not lock galleries.

---

## 2. Database changes

**Studio name in gallery links.** Revision **`b7c3e9a1d5f2_studio_slug`** (down_revision `a9d3c5e7b1f4`) adds `studios.slug` (unique), backfilled from each studio's name (`Acme Photo` → `acme-photo`, duplicates `-2`, `-3`; names such as `admin` or `api` that the app itself uses get `-studio`). New studios get theirs at creation (`studio_slug.build_studio_slug`). Renaming a studio keeps its slug, so links already sent never break. Clients see `/<slug>/gallery/<link id>`; `ClientResponse.gallery_url_path` and the client list return that path.

A second revision, **`f3b8d1a6c9e4_studio_storage_prefix`** (down_revision `e5a1b9c7d3f2`), adds `studios.storage_prefix` (the studio's permanent readable folder in R2; NULL for existing studios, which keep `studios/{id}`) and widens the storage path columns (`clients.drive_folder_id`, `clients.thumbnail_folder_id`, `albums.drive_folder_id`, `upload_sessions.drive_file_id`, `upload_sessions.thumbnail_drive_file_id`) from 255 to 512 characters. It is reversible and verified on MySQL 8 (upgrade, `alembic check`, downgrade, re-upgrade).

The first revision, **`e5a1b9c7d3f2_multi_studio_foundation`** (down_revision `d3a7c9e1b5f6`):

* **New tables:** `studios` (name, contact_email/phone, logo_url, brand_color, status, `quota_bytes`, `used_bytes`, `reserved_bytes`, timestamps), `platform_storage` (single row `id=1`: platform `used_bytes`, `reserved_bytes`; seeded by the migration).
* **`admins`:** `+role` (`super_admin|studio_admin`, existing rows → `studio_admin`), `+studio_id`, `+session_version`, `+company_name`, `+contact_phone`, `+logo_url` (the super admin's company profile; migration `c9e4a7b2d6f1`).
* **`studio_id`** (nullable FK `ON DELETE RESTRICT`, indexed) on `clients`, `albums`, `media`, `upload_sessions`, `download_jobs`, `download_records`. `studio_settings.studio_id` (unique, CASCADE).
* **`media`:** `+storage_key`, `+storage_provider`.
* **`upload_sessions`:** `+reserved_bytes`, `+reservation_status` (`none|reserved|committed|released`).
* **`audit_logs`:** `+studio_id` (SET NULL), `+actor_role`, `+metadata` (JSON).
* Fully reversible (`alembic downgrade -1`). The migration logs a warning with the number of unmapped legacy rows.

Verified on a real MySQL 8.0: upgrade of the full chain with legacy data (row counts preserved, `studio_id` NULL, role `studio_admin`), `alembic check` (no model/migration drift), `downgrade -1` and re-upgrade.

### Units: decimal TB vs binary TiB
All sizes are **bytes** (BIGINT). Defaults are **decimal**: `PLATFORM_CAPACITY_BYTES = 1 TB = 10^12 = 1,000,000,000,000` and `DEFAULT_STUDIO_QUOTA_BYTES = 10 GB = 10^10`. A binary TiB is `1,099,511,627,776` bytes (~10% more). If your storage provider bills in binary units, set `PLATFORM_CAPACITY_BYTES` explicitly. The API never converts; clients format for display.

---

## 3. Migrating an existing installation (runbook)

The migration cannot know which studio the existing data belongs to, so it does
**not guess**: existing rows get `studio_id = NULL` and existing admins are
`studio_admin` with no studio. Until mapped, those admins receive
`403 STUDIO_NOT_ASSIGNED` on `/api/admin/*`.

1. **Back up the database** (`mysqldump --single-transaction gallery > backup.sql`). Stop the app or put it in maintenance.
2. `pip install -r requirements.txt` (adds `email-validator`, `boto3`) and add the new variables to `.env` (§6). **Files are not migrated automatically:** this version stores everything in R2 (the Google Drive backend is gone), so a fresh start is assumed; existing Drive-hosted files are not copied.
3. `alembic upgrade head`
4. Create the platform owner: `python -m app.create_super_admin` (prompts; min 4 chars; password only hashed).
5. Map the legacy data. Always dry-run first (the default):
   ```
   python -m app.legacy_to_studio                       # report: unmapped rows/bytes, existing studios
   python -m app.legacy_to_studio --create-studio "My Studio" --quota-bytes 500000000000 --contact-email me@x.com
   python -m app.legacy_to_studio --create-studio "My Studio" --quota-bytes 500000000000 --apply
   ```
   Options: `--studio-id N` (map into an existing studio), `--client-ids 1,2,3` and `--admin-ids 1,2` (split a legacy install across several studios, run once per studio). It **refuses** (changes nothing) if the legacy media bytes do not fit the studio quota, copies the legacy `studio_settings` row, recomputes `used_bytes`, and is idempotent.
6. `python -m app.reconcile_quota` should report everything in sync (exit code 1 on drift; `--apply` repairs).
7. Start the app, log in as the studio admin and as the super admin.

Rollback: `alembic downgrade -1` (or restore the backup).

### 3b. One login per studio — migration `a9d3c5e7b1f4` and cleanup of existing data

Rule: **one studio = exactly one studio login** (`admins.studio_id` is unique; super admins and unmapped legacy rows have `studio_id` NULL, which the index allows many of). The migration replaces the plain index `ix_admins_studio_id` with the unique index `uq_admins_studio_id`.

* **It never deletes or edits an account and never fails your deploy.** If every studio already has at most one login, `alembic upgrade head` simply creates the unique index. If some studio has more than one, the migration **prints a warning naming them and leaves the schema unchanged**; the app still runs (the service layer already refuses new second logins), and you clean up with the tool below.
* **Check first** (read-only, changes nothing): `python -m app.consolidate_studio_logins` — lists every studio with more than one login: id, name, email, status, created, last login, uploads in flight.
* **Choose which account each studio keeps**, then apply (a dry run is printed unless `--apply`):
  ```
  python -m app.consolidate_studio_logins --keep 3:12 --keep 7:20          # STUDIO_ID:ADMIN_ID, repeatable
  python -m app.consolidate_studio_logins --keep-oldest                    # or --keep-newest, for every listed studio
  python -m app.consolidate_studio_logins --keep 3:12 --keep 7:20 --apply
  ```
  For each account that is **not** kept (default `--action detach`): its in-flight upload reservations are released (quota goes back), it is **disabled**, `session_version` is bumped (its sessions and cookies stop working at once) and it is **detached** from the studio (`studio_id` NULL) — the row, its email and its audit history stay, so it can be reviewed and removed later by hand. `--action delete --yes` removes the account (and its upload-session rows) instead. Each change is audited as `studio_login_consolidated` (actor `system`), everything runs in one transaction, and clients, albums, photos, videos, storage objects, quotas and audit logs are never touched.
* When no studio is left with more than one login the tool **creates the unique index** itself (`--ensure-index` does only that on an already-clean database). Re-running it is safe.
* `python -m app.legacy_to_studio` now refuses (changes nothing) to map more admins into a studio than it can hold; pick exactly one with `--admin-ids`.
* Rollback: `alembic downgrade -1` restores the plain index (accounts are not changed).

---

## 4. API

Error envelope unchanged: `{success:false, error:{code,message}}`. Lists use the existing `{items,page,limit,total,has_more}` page shape.

### Super admin — `/api/super-admin` (role `super_admin` only → else `403 SUPER_ADMIN_REQUIRED`)
| Method & path | Purpose |
|---|---|
| `GET /stats` | Platform stats: studio counts, capacity/allocated/used/reserved bytes, unmapped legacy row counts |
| `GET /studios` (`page,limit,search,status`) · `POST /studios` | List / create studio **+ first studio admin in one transaction**. Without `admin_password` a one-time temporary password is returned (`Cache-Control: no-store`) |
| `GET /studios/{id}` · `PUT /studios/{id}` | Detail with counts / update name, contact, branding |
| `POST /studios/{id}/logo` · `DELETE /studios/{id}/logo` | Upload (multipart field `file`: PNG/JPEG/WebP/GIF, max 5 MB) / remove the studio's logo image. The image is checked, re-encoded to a PNG that fits 512 px (metadata stripped; SVG is refused) and stored in R2 at `studios/{id}/branding/logo-{hash}.png`. Audited as `studio_logo_updated` / `studio_logo_removed` |
| `POST /studios/{id}/suspend` · `POST /studios/{id}/reactivate` | Status change (optional `reason`) |
| `DELETE /studios/{id}` | Delete a studio — only when it is **suspended**. By default it must also hold **no clients/albums/media or storage** (`409 STUDIO_NOT_SUSPENDED` / `STUDIO_NOT_EMPTY`); that removes the studio row, **its one login**, its settings and its logo image. With `?delete_data=true&confirm_name=<exact studio name>` (`400 CONFIRMATION_MISMATCH` otherwise) it deletes the studio **and all of its data**: clients, albums, media rows, comments, favourites, download history and upload sessions in one transaction (children first, platform storage ledger credited back), then every stored object of the studio (originals, thumbnails, logo, anything under its own `studios/<name>-<id>/` folder; each key is checked to belong to this studio). Storage failures after the commit are reported as `storage_failures` and cleaned later with `python -m app.reconcile_orphans`. Audit rows are kept (`studio_deleted`, with the counts when data was deleted) |
| `PUT /studios/{id}/quota` | Set quota. `409 QUOTA_BELOW_USAGE` if below used+reserved |
| `GET /studios/{id}/usage` | quota / used / reserved / remaining |
| `GET /studios/{id}/admins` · `POST /studios/{id}/admins` | The studio's login (0 or 1 item) / **recovery only**: give a studio that has **no** login its one login. **One login per studio** is enforced in the service (`409 STUDIO_USER_LIMIT` when the studio already has any login, disabled ones included) **and** by the database (unique index `uq_admins_studio_id` on `admins.studio_id`). The login is created together with the studio (`POST /studios`) |
| `PUT /studios/{id}/admins/{admin_id}` | Edit the login's name and/or sign-in email (either alone; email unique; an email change signs the login out) |
| `POST /studios/{id}/admins/{admin_id}/disable` · `POST .../enable` | Disable (signed out at once, cannot sign in, nothing deleted) / re-enable the studio login |
| `POST /studios/{id}/admins/{admin_id}/reset-password` | Secure reset: new temp password returned once, old password and all old sessions invalidated |
| `GET /audit-logs` (`studio_id,action,from,to,category,actor,search,sort,page,limit`) · `GET /audit-logs/export` | Platform-wide audit trail with filters and a summary; CSV export of the same filter (max 10,000 rows, audited) |
| `POST /change-password` | The signed-in super admin changes their own password (`current_password`, `new_password`, min 4). Other sessions are signed out, this one stays; audited as `super_admin_password_changed` |

### Studio admin — `/api/studio` (studio always taken from the logged-in admin)
`GET/PUT /profile` (name, contact, logo, brand colour only — never quota/status), `GET /usage`, `GET /audit-logs`.

### Studio logo — `GET /api/studios/{id}/logo?v=…` (public, no login)
Serves the studio's uploaded logo. A studio's `logo_url` is the same-origin path to this route (`/api/studios/{id}/logo?v={hash}`); the hash changes on every upload, so a replaced logo is never shown stale and the response is cached for a year. A removed or replaced version returns `404 LOGO_NOT_FOUND`. A `logo_url` that is a plain `https://` address (set through the API before uploads existed) still works and is shown as is. No database migration is needed — it reuses `studios.logo_url`.

### Existing routes — `/api/admin/*`, `/api/client/*`, `/api/auth/*`
Same paths, request and response shapes. Now: studio-scoped, role-gated, suspension-aware. Additive response fields only: login/`/me` return `role`, `studio_id`, `studio_name`; the dashboard returns `studio_quota`; upload start can now return `413 STUDIO_QUOTA_EXCEEDED`, `507 PLATFORM_CAPACITY_EXCEEDED` or `403 STUDIO_SUSPENDED`.

### Permission matrix (summary)
| Action | super_admin | studio_admin (own studio) | studio_admin (other studio) | client |
|---|---|---|---|---|
| Create/suspend studios, set quota, reset admin password | ✅ | ❌ 403 | ❌ 403 | ❌ |
| Studio profile / branding | ✅ (any) | ✅ (own) | 404 | ❌ |
| Clients, albums, media CRUD | ❌ 403 | ✅ (writes blocked if suspended) | 404 | ❌ |
| Upload | ❌ | ✅ within quota | 404 | ❌ |
| View gallery | ❌ | ✅ | 404 | ✅ own galleries only |

---

## 5. Storage quota enforcement

Counters live in `studios.used_bytes / reserved_bytes` and the single `platform_storage` row. **Remaining = quota − used − reserved** (computed, never stored).

```
POST /api/admin/media/upload-session   (declares file_size)
  └─ one DB transaction:
       1. CAS on upload_sessions.reservation_status  none|released → reserved   (idempotent for retries)
       2. UPDATE studios  SET reserved += n
            WHERE id=? AND status='active' AND used+reserved+n <= quota_bytes    → 413 STUDIO_QUOTA_EXCEEDED / 403 suspended
       3. UPDATE platform_storage SET reserved += n
            WHERE used+reserved+n <= PLATFORM_CAPACITY_BYTES                     → 507 PLATFORM_CAPACITY_EXCEEDED (whole txn rolled back)
  └─ only then is a presigned/resumable URL issued
browser ──PUT──▶ storage   (server never sees bytes)
POST /api/admin/media/upload-complete
  ├─ ownership guards (R2 key prefix; the legacy Drive client used an appProperties upload id)
  ├─ size and type taken from the STORAGE provider (get_file), never from the browser's claim
  └─ ONE transaction: insert Media, reserved −= r, used += actual, session → completed
       (object bigger than reserved ⇒ extra bytes reserved under the same limits; refused ⇒ object deleted, reservation released)
Failure / abandon / cancel / stale sweep / album or client delete  ⇒ release reservation (CAS, so it can only happen once)
Delete media/album/client: storage delete FIRST; usage decreases only after it succeeded (clamped at 0)
```

* Each step is a single conditional `UPDATE … WHERE` statement, so two concurrent uploads cannot both pass a check that only one fits (row-level atomicity on MySQL/InnoDB).
* Duplicate completion calls and retries are safe: the reservation state machine (`reserved → committed|released`) is compare-and-set; a second completion cannot create a second Media row or double-count.
* `python -m app.reconcile_quota [--apply] [--studio-id N] [--verify-objects]` recomputes the counters from the `media` / `upload_sessions` tables, releases stale reservations (older than `UPLOAD_RESERVATION_TTL_MINUTES`), and optionally compares recorded sizes with the provider. Run it from cron (e.g. nightly, report only) and alert on exit code 1.
* **R2 does not enforce per-studio quotas** — this application layer is the only enforcement; the signed `ContentLength` on R2 presigned URLs makes the provider reject bodies that differ from the reserved size.

---

## 6. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PLATFORM_CAPACITY_BYTES` | `1000000000000` | Total sellable storage (decimal 1 TB) |
| `DEFAULT_STUDIO_QUOTA_BYTES` | `10000000000` | Quota for new studios (10 GB) |
| `UPLOAD_RESERVATION_TTL_MINUTES` | `120` | Max life of an unfinished upload's reservation |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | – | Required — Cloudflare R2 is the only storage backend (Google Drive is no longer used or configurable; `GOOGLE_DRIVE_*` and `STORAGE_PROVIDER` lines left in an old `.env` are ignored, as are the old resumable-upload tuning variables `UPLOAD_MAX_CONCURRENT`, `UPLOAD_CHUNK_SIZE_MB`, …). **Server-side only**; never expose to a frontend |
| `R2_ENDPOINT_URL` | `https://<account>.r2.cloudflarestorage.com` | Override only if needed |
| `R2_PRESIGN_TTL_SECONDS` | `900` | Lifetime of a presigned upload URL |

Existing variables are unchanged (`.env.example` lists them all). `CORS_ORIGINS` and `DEV_FRONTEND_ORIGIN` must include the frontend origin (`http://localhost:5173` in development). `DEV_FRONTEND_ORIGIN` is required.

### Cloudflare R2 setup
1. Create a **private** bucket; create an R2 API token scoped to that bucket with **Object Read & Write** (a read-only token passes the read checks but fails every write with `AccessDenied`).
2. Set the R2 variables above; restart. `python -m scripts.check_r2` proves the keys, bucket, write access and presigned uploads actually work (`--read-only` to avoid writing); `python scripts/check_env.py` also covers the rest of `.env`.
3. Add a **CORS policy** on the bucket (R2 → bucket → Settings → CORS Policy). Browsers upload straight to R2, so it must allow the frontend origin(s) to `PUT`; reads go through the backend, so nothing else is needed:
   ```json
   [{ "AllowedOrigins": ["http://localhost:5173"], "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["*"], "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 3600 }]
   ```
   Add the production frontend origin too. Without this rule uploads fail in the browser with a CORS error ("No 'Access-Control-Allow-Origin' header").
4. Object keys all start with the studio's own readable folder, `studios/{studio-name}-{studio_id}/` (saved once in `studios.storage_prefix` when the studio is created; renaming the studio never moves files) — originals at `{studio folder}/albums/{client-name}_{album_id}/{media_uuid}`, thumbnails under `{studio folder}/{client folder}/Thumbnails/`, the logo at `{studio folder}/branding/logo-{hash}.png`. Studios that predate this keep `studios/{id}/…`. The full layout is in `STORAGE_STRUCTURE.md`. The API refuses any key outside the calling studio's folder.
5. The upload path was verified end to end in a browser against an S3-compatible stand-in, and the provider is unit-tested against a fake S3 client. Still do a smoke test against your real bucket (`check_r2`, then one upload) before production.

---

## 7. Audit log

Recorded with actor, role, studio, action, time and sanitised metadata: studio created/updated/suspended/reactivated, quota changes, admin created, password reset, media upload (success and failure), media/album/client deletion, login success and **failure**. `audit_service.sanitize_metadata` drops any key containing `password, token, secret, credential, cookie, authorization, api_key, access_key, private, session` and anything that is not a short scalar, so plaintext passwords, tokens and storage credentials cannot be stored. Failed logins store neither the attempted password nor the attempted email.

---

## 8. Frontend (one app)

There is a single React app, `frontend/`. The Super Admin console is part of it, under `/super-admin/*`, and uses the same login page (`/admin/login`) and the same session cookie as the studio admin area, so no extra origin or CORS entry is needed.

* Sign in at `/admin/login`. `POST /api/auth/admin/login` returns `role`; a `super_admin` is sent to `/super-admin/dashboard`, a studio admin to `/admin/dashboard` (unchanged).
* `RequireAdmin` sends a super admin who opens `/admin/*` to the console; `RequireSuperAdmin` sends a studio admin who opens `/super-admin/*` back to `/admin/dashboard`. These are UX guards only — the API enforces the role on every route (`403 SUPER_ADMIN_REQUIRED` / `STUDIO_ADMIN_REQUIRED`).
* Console pages: dashboard, studios (list/create, with per-row **Edit** (details + quota) and **Users** (add, edit, reset password, disable/enable, delete) dialogs), studio detail (quota, details with a **logo image upload** (preview / replace / remove), suspend/reactivate, admins), audit log, and a Settings page where the super admin changes their own password. The console is styled like the studio dashboard (same sidebar, search pill and profile menu); all its CSS is `sa-` prefixed and scoped, so it cannot affect the studio pages.
* **Studio actions** (studios list **More ▾**, and the studio detail page): **Suspend / Reactivate studio** and **Delete studio**. Delete is greyed out ("Suspend the studio first") until the studio is suspended. The dialog deletes an empty studio by default; ticking **Also permanently delete all of this studio's clients, albums, photos and videos** switches it to *Delete studio and all its data*, which stays disabled until the exact studio name is typed. Clients of a deleted studio lose their galleries; there is no undo.
* **One studio = one login = one studio dashboard**: a studio gets its single login when it is created (**New studio**: studio name, contact email, phone, logo, quota, login name, login email, password — a generated password is shown once). The console has no *Add user*, *Manage all users* or *Delete user*; the API refuses a second login (`409 STUDIO_USER_LIMIT`), the database refuses it (unique `admins.studio_id`), and `DELETE /studios/{id}/admins/{admin_id}` no longer exists. *Set up login* is offered only for a studio that has no login at all.
* **Login button on the studios list**: **Login ▾** opens a menu straight away showing the studio's login (name, email, Active/Disabled) and **Edit login details**, **Change login email**, **Reset password**, **Disable login / Enable login**. The studio detail page shows the same login as a **Studio login account** section with the same four buttons. Same dialogs and API calls everywhere; the studios list refreshes after any change.
* **Menus** are drawn above dialogs and tables (never clipped), close on outside click or Escape (Escape closes only the menu, not a dialog).
* **Session handling**: changing the login email, resetting the password or disabling the login bumps `admins.session_version`; every studio request re-reads it, so the studio is signed out on its next request. Editing only the name does not sign anyone out. **Deleting a studio deletes its login** (and cancels that login's in-flight upload reservations). Gallery clients are a separate thing and are never affected by any login action.
* **Reset password** (studio login → Reset password): the dialog opens **empty**; a password is created only when the super admin clicks **Generate** (12 characters, from the browser's secure random source) or types one, and **Update password** stays disabled until something has been entered (minimum 4 characters). Show/Hide and Copy are available. The studio login's *current* password can never be displayed — it is stored only as an Argon2 hash — so the dialog says so. Saving signs the studio out everywhere (`session_version`) and is audited as `studio_admin_password_reset`. (A generated password at studio creation, or at *Set up login*, is shown once in a copy dialog.)
* Run: `cd frontend && npm run dev`. Create the first platform owner with `python -m app.create_super_admin`.
* The earlier separate `super-admin/` app is obsolete and can be deleted.

**Studio dashboard:** the studio admin sidebar, the mobile top bar and the dashboard's profile menu show the studio's own **name and logo**, read from `GET /api/studio/profile` (a studio without a logo shows its name, and the profile chip an initial). They used to be the hard-coded "Love Story" mark.

**Uploads from the studio area:** the Uploads page asks for a presigned URL and the browser PUTs the file straight to R2 (`adminService.uploadToDrive` — name kept from the Drive era). R2 replies to a PUT with an empty body, so the frontend no longer parses a response; the server uses the key it issued. The browser sends the file itself, so the `Content-Length` it sends is the one the server signed.

**Client galleries:** a client who opens a shared link (`/<studio slug>/gallery/<client uuid>`; the older `/gallery/<client uuid>` redirects to it) sees the **sharing studio's own logo, name and contact details**, not the Love Story brand: the entrance (password) page, the gallery/wishlist/album header and the gallery footer (name, contact email and phone). The data comes from an additive `studio` object (`name`, `logo_url`, `brand_color`, `contact_email`, `contact_phone`) on `GET /api/client/gallery/access/{id}` (public, so the entrance page can brand itself before login) and `GET /api/client/gallery`; it is read live, so a renamed studio or replaced logo shows at once, and it is still returned for a suspended studio. A studio without a logo shows its name in script lettering; a legacy client not mapped to a studio (`studio: null`) keeps the original Love Story look. Nothing else about the studio (quota, other clients) is exposed.

**Super admin dashboard:** count-only cards (studios, clients, albums, files, stored, downloads); a *Platform activity* area chart with tabs (uploaded data, new files, new clients, new albums, downloads) and hover values; a *Platform storage* donut (stored / reserved / remaining, capacity, allocated, oversold warning); *Library mix* (photos vs videos, active vs suspended studios); *Most active studios* (uploads in the range); and recent activity. Options: 7 / 30 / 90 day range (remembered in the browser), Refresh, and *Export studios* (CSV of every studio's quota and usage). Charts are plain SVG (no chart library). Data: the existing `GET /api/super-admin/stats` plus the new read-only `GET /api/super-admin/stats/trends?days=7|30|90` (daily new studios/clients/albums/files, bytes uploaded, downloads and bytes downloaded for the range and the same-length period before it, photo/video totals, five most active studios; any other `days` value becomes 30; super admin only).

**Super admin sidebar pages:** *Studio logins* (`/super-admin/logins`, `GET /api/super-admin/logins`: every studio's single login with status, last sign-in and read-only list) and *Storage* (`/super-admin/storage`: platform capacity and every studio's allowance with search/filter/sort and per-studio quota editing). The usage-check endpoints `GET`/`POST /api/super-admin/storage/reconcile` (compare the counters with the real files, repair them, audited as `storage_counters_repaired`) remain in the API but have no button in the console. See `SUPER_ADMIN.md` sections 4.7 and 4.8.

**Remaining gaps in the studio area** (not built yet): (a) a logo upload in the *New studio* dialog and in the studio admin's own Settings (today only the super admin sets the logo, from Edit studio or the studio detail page), (b) a quota bar fed by `GET /api/studio/usage` on every page (the dashboard already receives `studio_quota`), (c) friendlier UI for the new upload errors `413 STUDIO_QUOTA_EXCEEDED`, `507 PLATFORM_CAPACITY_EXCEEDED`, `403 STUDIO_SUSPENDED` and for disabling write actions while a studio is suspended, (d) a studio branding/profile page on `/api/studio/profile`, (e) a `/api/studio/audit-logs` view. **Done:** the studio's Storage page, dashboard and Downloads cards no longer show "Server disk (VPS)" or "Google Drive quota"; they show the studio's own allocation (quota / used / remaining / reserved by uploads, decimal units like the super admin console), and `GET /api/admin/storage` no longer returns `vps_disk` or `drive_quota` (it returns `studio_quota`).

---

## 9. Tests

New suites (`tests/test_multi_studio_*.py`, helpers in `tests/ms_helpers.py`, 130 tests): super-admin management (incl. studio logo upload/remove, login edit/disable, one-login-per-studio at the API and database level, studio delete rules incl. delete-with-all-data (`test_multi_studio_purge.py`), own-password change, dashboard trends `test_multi_studio_dashboard_trends.py`, studio logins list and storage check/repair `test_multi_studio_logins_storage.py`, audit log options and export `test_multi_studio_audit_options.py`, studio name in gallery links `test_multi_studio_gallery_urls.py`, Settings account `test_multi_studio_super_admin_account.py`), login consolidation tool and migration safety, tenant isolation (IDOR across URL/body/query/bulk), suspension, client access (incl. the sharing studio's branding on the client gallery, `test_multi_studio_client_branding.py`), quota reserve/commit/release, over-quota and over-capacity rejection, concurrent reservations (threads on separate connections), duplicate completion, deletion accounting, reconciliation, R2 provider with a fake S3 client (incl. that client folders are created under `studios/{id}/`), legacy mapping. Run: `pytest tests/test_multi_studio_*.py`.

Concurrency tests use a temp file SQLite by default; set `CONCURRENCY_TEST_DATABASE_URL=mysql+pymysql://user:pw@host/db` to run them against MySQL (they create/drop tables in that database — use a scratch one).

`conftest.py` places rows created without a `studio_id` into a default studio (id 1) so the pre-existing tests, which know nothing about studios, keep running. This is test-only.

---

## 10. Known limitations / remaining work before production

* **106 pre-existing test failures** (identical before and after this work; suite: 322 pass / 106 fail, 428 total): these tests call the removed `/api/admin/media/upload` endpoint and the old resumable upload helpers. They were left untouched; they cannot validate the new upload path, which is covered by the new suites instead. They should be rewritten or deleted.
* **Verification status:** the R2 provider is unit-tested against a fake S3 client, and the browser upload flow (session → presigned PUT → thumbnail → confirm → view/download → delete) was exercised end to end against an S3-compatible stand-in. It still needs a smoke test against your real bucket: the API token must be **Object Read & Write** and the bucket needs the CORS rule from §6 (`python -m scripts.check_r2` checks the former).
* **R2:** files > 5 GiB need multipart upload (not implemented; refused with a clear error); `move_file`/`rename_folder` are no-ops (keys keep their original album segment, membership lives in the DB). A browser cannot redirect an upload, because the server uses the key it issued.
* **Thumbnails** are not counted in `Media.file_size` and therefore not in quota. They live in the client folder, so deleting a single album leaves its photos' thumbnails behind until the client (or each photo) is deleted.
* **Studios created before readable folders** (`storage_prefix` NULL) keep the plain `studios/{id}/albums/{album_id}/…` layout, where deleting an album does not remove its original files from R2 (they are only removed when each photo is deleted). New studios use one folder per album, which is removed together with the album.
* **Old Google Drive code** (`google_drive_service.py`, `circuit_breaker.py`, `retry.py`, `thumbnail_folder_migration.py`, `migrate_thumbnail_folders.py`, the `google-*` pip packages) is dormant but still in the repository; the old separate `super-admin/` frontend folder is obsolete and can be deleted.
* Unmapped legacy clients (`studio_id` NULL) can still view galleries until mapped; legacy admins are locked out until `legacy_to_studio` is run.
* `app/create_admin.py` is the old single-studio CLI (minimum 4 characters); use `create_super_admin` for platform owners and the super-admin console/API for studio admins.
* **No login rate limiting** while passwords may be as short as 4 characters — add rate limiting on login and super-admin endpoints, MFA for super admins, and monitoring on `reconcile_quota` before going live. MySQL row-lock behaviour was exercised by the thread-based concurrency tests (MySQL 8) but not load-tested.
* Take a database backup before every production migration.
