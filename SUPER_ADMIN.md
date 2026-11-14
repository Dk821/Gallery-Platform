# Super Admin Guide — options, data and flows

This document explains the **Super Admin console** (`/super-admin/*`) of LoveStory PH: who the super admin is,
every screen and option, what data is behind each option, and how the main flows work from click to database.

Related documents: `MULTI_STUDIO.md` (tenancy, quotas, migration runbook), `STORAGE_STRUCTURE.md`
(where files live in R2), `ARCHITECTURE.md` (whole system), `README.md` (setup).

---

## 1. What the Super Admin is (and is not)

The super admin is the **platform owner / operator**. They manage *tenants* (photography studios), their
*storage quotas*, their *sign-in accounts* and the *audit history*. They do **not** work inside a studio.

| | Super admin | Studio admin | Client |
|---|---|---|---|
| Signs in at | `/admin/login` → lands on `/super-admin/dashboard` | `/admin/login` → lands on `/admin/dashboard` | `/{studio-name}/gallery/{galleryId}` |
| Belongs to a studio | No (`studio_id` is empty) | Exactly one studio | A studio's client |
| Creates / suspends studios, sets quotas | **Yes** | No | No |
| Creates a studio with its one login; edits / resets / disables that login | **Yes** | No | No |
| Sees clients, albums, photos of a studio | **No** (only counts) | Yes, own studio only | Own albums only |
| Uploads photos | No | Yes (within the studio quota) | No |

Hard rules enforced by the API (not only by the UI):

* Every `/api/super-admin/*` route requires the `super_admin` role. The role is **re-read from the database on every
  request** — it is never trusted from the cookie or from anything the browser sends. A studio admin gets `403`.
* A super admin gets `403` on `/api/admin/*` (the studio routes), so there is no way to browse a studio's galleries
  through the console.
* A studio user addressed through the wrong studio's URL is a `404` (the id in the URL is never trusted on its own).

---

## 2. Getting in

| Step | Detail |
|---|---|
| Create the first super admin | `python -m app.create_super_admin` (prompts for name, email, password; minimum 4 characters; password is hashed with Argon2 and never printed) |
| Sign in | `/admin/login` with that email + password. A super admin is redirected to `/super-admin/dashboard` |
| Session | Signed cookie, valid for 24 hours (`SESSION_TTL_MINUTES`, default 1440). The cookie also carries a `session_version`; bumping it (password change/reset, disable) signs that account out everywhere at once |
| Sign out | **Sign out** at the bottom of the sidebar |
| Failed sign-ins | Recorded as `admin_login_failed` in the audit log (the attempted password is never stored) |

---

## 3. Console map

```
/super-admin
 ├─ /dashboard            count cards, activity chart, storage, studio breakdowns, recent activity
 ├─ /studios              All studios: search, filter, New studio, Edit, Login ▾, More ▾
 ├─ /studios/:studioId    One studio: counts, quota, details + logo, users, recent activity, suspend/reactivate
 ├─ /logins               Studio logins: every studio's single login, with reset / disable / change email
 ├─ /storage              Storage: platform capacity, every studio's allowance, quota editing
 ├─ /audit-logs           Platform-wide audit trail: categories, search, presets, sort, auto-refresh, CSV export
 └─ /settings             Your account + change your own password
```

Sidebar: **Dashboard** · **Studios**, **Studio logins** (Management) · **Storage** (Operations) · **Audit log** (Insights) · **Settings** (System) · **Sign out**.
The top bar only holds the account menu; search lives on each list page (Studios, Studio logins, Storage, Audit log).

---

## 4. Screen by screen

### 4.1 Dashboard (`/super-admin/dashboard`)

| Block | Shows | Data source |
|---|---|---|
| Notice (only when needed) | "Legacy rows not yet assigned to a studio" — non-zero means `python -m app.legacy_to_studio` still has to be run | `unmapped_legacy_rows` (admins / clients / albums / media with no studio) |
| Header options | **7d / 30d / 90d** range (remembered in the browser), **Refresh**, **Export studios** (CSV: quota, stored, reserved, remaining, used %), **New studio**. Shows when the data was last updated | `GET /stats/trends?days=` |
| KPI cards | Six count-only cards: **Studios**, **Clients**, **Albums**, **Media files**, **Stored** (size), **Downloads** (in the selected range) | `GET /stats` + `GET /stats/trends` |
| Platform activity (chart) | Area chart per day with tabs **Uploaded data / New files / New clients / New albums / Downloads**, hover values and the period total with change. Days are UTC | `GET /logins` | Studio logins page | `page`, `limit` (≤200), `state` = active / disabled / none, `search` (studio, login name or email). Returns one row per studio with `login` (or null) and its last sign-in, plus `summary` counts for the filter chips |
| `GET /storage/reconcile` | Usage check (report only) | Studios whose counters differ from the real files or that are over quota; the platform total's in-sync flag |
| `POST /storage/reconcile` | Repair counters | Recalculates the counters from the real rows; returns the state afterwards (`repaired_studios`). Audited |
| `GET /stats/trends` |
| Platform storage | Donut of stored / reserved (in-flight uploads) / remaining, plus capacity and **allocated quota** (sum of all studio quotas). A warning appears at 80% full and when allocated > capacity (allowed on purpose — "overselling" — but the platform limit then stops uploads first) | `platform_storage` row + `platform_capacity_bytes` setting (default 1 TB) |
| Library mix | Photos vs videos (files and size) and active vs suspended studios | `GET /stats/trends`, `GET /stats` |
| Most active studios | Top 5 by data uploaded in the selected range | `GET /stats/trends` |
| Recent activity | Latest 10 audit events (only 10 are ever shown) | `GET /audit-logs?limit=10` |

### 4.2 Studios list (`/super-admin/studios`)

Columns: **Studio** (name, links to its detail page) · **Status** · **Storage** (used / quota bar) · **Contact**
(the studio's contact email) · **Created** · actions **Edit**, **Login ▾** and **More ▾**.

| Option | What it does |
|---|---|
| Search box | Filters by **studio name** (case-insensitive). *Note: the placeholder says "name or email", but the API currently matches the studio name only* |
| Status filter | All statuses / Active / Suspended |
| Pagination | 20 per page |
| **New studio** | Creates a studio **and its one studio login** together: studio name, contact email, phone, logo (optional), storage quota, login name, login email, password (see §5.1) |
| **Edit** | Dialog with the studio's details, logo and storage quota (same forms as the detail page) |
| **More ▾** | **Suspend studio** / **Reactivate studio**, and **Delete studio** (greyed out with "Suspend the studio first" until the studio is suspended) |
| **Login ▾** | Opens a menu straight away showing the studio's login (name, email, Active/Disabled) and its actions — see §4.4. There is no *Add user*, *Manage all users* or *Delete user* |

### 4.3 Studio detail (`/super-admin/studios/:studioId`)

| Block | Options / data |
|---|---|
| Header | Name, status badge, created date, contact email, logo. **Suspend studio** (asks for an optional reason) or **Reactivate studio**; when suspended also **Delete studio** (§5.2b) |
| Suspended notice | "Its admins can view data but cannot upload, delete or edit, and its clients cannot open their galleries" |
| Counts | Studio logins (always 1), Clients, Albums, Media files (numbers only — never the content) |
| Storage quota card | Set the quota as a number + unit (decimal: 1 GB = 10⁹ bytes). Shows used / reserved and the **minimum allowed** (what the studio currently holds) |
| Studio details | Name, contact email, contact phone, **logo upload / replace / remove** (the brand colour is not shown in the console; a colour already stored is kept) |
| Studio login account | The studio's one login: name, email, status and the buttons **Edit login details · Change login email · Reset password · Disable login / Enable login**. Only a studio with no login at all (an older studio) shows **Set up login** instead |
| Recent activity | That studio's latest audit events + link to the full audit log filtered to the studio |

### 4.4 Studio login account (menu on the list, section on the detail page)

**One studio = one login = one studio dashboard.** Every studio has exactly one studio-administrator login, created together with the studio. It is the only way into that studio's `/admin/*` dashboard (gallery *clients* are different: they open their private galleries with the gallery link + password and are not affected by anything on this page).

On the studios list, **Login ▾** shows the login (name, email, Active/Disabled) followed by the actions below. The studio detail page shows the same login as a **Studio login account** section with the same actions as buttons. Nothing offers *Add user*, *Manage all users* or *Delete user* — the API refuses them too.

| Action | What happens | Audit action |
|---|---|---|
| **Edit login details** | Change the login's **name**. Does not sign anyone out | `studio_admin_updated` |
| **Change login email** | New sign-in email (valid, unique across the platform, stored lower-case). **The studio is signed out everywhere**; the old address stops working at once | `studio_admin_updated` |
| **Reset password** | Dialog opens **empty**. Press **Generate** (12 characters, browser's secure random) or type one (min 4). Saving **signs the studio out everywhere**. The *current* password can never be shown — only its Argon2 hash is stored | `studio_admin_password_reset` |
| **Disable login** / **Enable login** | Disable: signed out immediately and cannot sign in; nothing is deleted and clients keep their gallery access. Enable: signs in again with the current password | `studio_admin_disabled` / `studio_admin_enabled` |
| **Set up login** | Only for a studio that has **no** login (e.g. an older studio whose login was detached by the cleanup tool, §11). Name, email, optional password (generated + shown once if empty). Refused with `409 STUDIO_USER_LIMIT` when the studio already has one | `studio_admin_created` |

A studio login does not need a "delete" action: **deleting the studio deletes its login** (§5.2b). Disabling the login is the way to lock a studio out without touching its data.

---

### 4.5 Audit log (`/super-admin/audit-logs`)

Table columns: **When · Action · Studio (link) · Actor · Details**. Failed actions (`…_failed`) get a red marker and a
"failed" badge.

| Option | What it does |
|---|---|
| Search | Matches the action text, resource type, IP address, studio name, and (for a number) a resource or user id. `%` and `_` are plain characters |
| Studio · Who | Studio dropdown (`?studio=<id>` pre-selects one) and **Everyone / Super admin / Studio admins / Clients** |
| Time | **Today (default)** · Any time · 7 days · 30 days · Custom (From / To dates). Days are the viewer's own calendar days: the page sends its UTC offset as `tz_offset`. "Clear filters" returns to Today |
| Sort · Page size | **Newest first / Oldest first**; **25 / 50 / 100 per page** (remembered in the browser) |
| Clear filters | Resets everything above (back to Today) |

The page shows the list only: there are no summary cards, activity-type chips, refresh or export buttons. The API still supports
`category`, `summary` and `/audit-logs/export` for future use.

The `Details` column shows small, non-sensitive context (for example the old and new quota, or the suspend reason).
Anything whose key looks like a secret (`password`, `token`, …) is dropped before saving.

### 4.6 Settings (`/super-admin/settings`)

* **Account**: edit your **name**, **sign-in email**, **company name** and **contact number**, and upload the company **logo**.
  A new email needs the current password and must not belong to another account (`PUT /account`); the top bar shows the new
  name straight away. Clearing the company name or contact number (sending it empty) removes it; the number may contain only
  digits, spaces and `+ - ( ) .`. The **logo** (PNG, JPG, WebP or GIF, up to 5 MB) is changed at once, separately from
  *Save changes* (`POST` / `DELETE /account/logo`): it is re-encoded like a studio logo, stored in R2 at
  `platform/branding/admin-{id}/logo-{hash}.png` and served publicly at `/api/platform/{id}/logo?v={hash}`. The logo and the
  company name appear at the top of the console sidebar (the mobile top bar too); with no logo the company name replaces
  "Platform", and with neither it reads "Platform / Console". Audited as `super_admin_account_updated` (only which fields
  changed, never the values) and `super_admin_logo_updated` / `super_admin_logo_removed`.
* **Preferences** (kept in this browser only): the Dashboard's range (7 / 30 / 90 days), what the Audit log opens on
  (Today by default, or 7 days / 30 days / Any time) and its rows per page (25 / 50 / 100).
* **Change password**: current password + new password + confirmation. Success signs out every *other* session of
  yours and keeps this browser signed in. Audited as `super_admin_password_changed` (no password material).
* The Settings page no longer shows a *Sign-ins and devices* card. The API behind it is still there (`GET /account` returns
  the last 10 sign-in attempts; `POST /sign-out-others` signs out every other browser and is audited as
  `super_admin_signed_out_other_devices`) but nothing in the console uses it now.

---

### 4.7 Studio logins (`/super-admin/logins`)

One row per studio with its single login: **Studio** (link, "suspended" badge) · **Login** (name, email) · **Status**
(active / disabled / no login) · **Last sign-in** (from the audit trail; "Never" if it has not signed in) · **Created** ·
no action buttons: the list is read-only (manage a login from the Studios list or the studio's page). Filter chips with counts: **All studios · Active logins · Disabled · No
login**; search by studio name, login name or email; 25 rows per page. A studio that still has two logins from before
the one-login rule shows one row per login, so it is easy to spot (clean it up with `python -m app.consolidate_studio_logins`).
No password or session data is ever sent to the page.

### 4.8 Storage (`/super-admin/storage`)

| Block | What it does |
|---|---|
| Platform capacity | Capacity, stored, reserved by uploads, remaining, allocated quota, oversold and 80%-full warnings (same numbers as the dashboard) |
| Studio allowances | Table of every studio: quota, stored, reserved, remaining, usage bar. Search, filter (all / nearly full 80%+ / suspended), sort (most storage / closest to quota / largest quota / name). **Edit quota** per studio |

## 5. Flows

### 5.1 Onboard a new studio

```
Super admin: Studios → New studio
   fields: studio name*, contact email, contact phone, logo (optional image), quota (number + unit; empty = default 10 GB),
           studio login: login name*, login email*, password (optional)
        │
        ▼  POST /api/super-admin/studios
 1. studios row created        status = active, used = 0, reserved = 0, quota = chosen/default
 2. storage folder fixed       storage_prefix = studios/{name-slug}-{id}   (never changes, even if renamed)
 3. the studio's one login    role = studio_admin, studio_id = this studio, password hashed (Argon2);
                               the database allows only ONE admin row per studio_id (unique index uq_admins_studio_id)
 4. audit row                  studio_created
 5. logo (if chosen)           uploaded right afterwards with POST /studios/{id}/logo (a failed upload does not undo the studio)
        │
        ▼
 Response contains temporary_password ONLY if the server generated it (leave the password empty to have one generated).
 The console shows it once in a copy dialog; it is never stored in plain text and never logged.
        │
        ▼
 Hand the email + password to the studio. They sign in at /admin/login → /admin/dashboard.
```

### 5.2 Suspend and reactivate a studio

```
Studio detail → Suspend studio (optional reason)      POST /studios/{id}/suspend    audit: studio_suspended {reason}
   │
   ├─ studio admins: can still sign in and READ (GET/HEAD/OPTIONS); every change → 403 STUDIO_SUSPENDED
   ├─ new uploads: refused (reservation fails with STUDIO_SUSPENDED)
   └─ clients: cannot sign in / open galleries while the studio is not active
Studio detail → Reactivate studio                     POST /studios/{id}/reactivate audit: studio_reactivated
   └─ everything works again; no data was touched
```

### 5.2b Delete a studio (empty, or together with all of its data)

Deleting is deliberately hard to do by accident: the studio must be **suspended**, and removing its data needs a tick **and** the studio's exact name typed.

```
Studios list → More ▾ → Suspend studio        (or Studio detail → Suspend studio)
Studios list → More ▾ → Delete studio         (or Studio detail → Delete studio)
        │
        ├─ A. box NOT ticked                   DELETE /api/super-admin/studios/{id}
        │     409 STUDIO_NOT_SUSPENDED   the studio must be suspended first
        │     409 STUDIO_NOT_EMPTY       it must hold no clients, albums or media, and show 0 used / 0 reserved storage
        │     → deletes the studio, its one login, its settings row and its logo image
        │
        └─ B. "Also permanently delete all of this studio's clients, albums, photos and videos" ticked
              type the exact studio name → button "Delete studio and all its data" becomes active
              DELETE /api/super-admin/studios/{id}?delete_data=true&confirm_name=<exact name>
              409 STUDIO_NOT_SUSPENDED · 400 CONFIRMATION_MISMATCH (wrong / missing name; nothing is deleted)
              In ONE database transaction (all or nothing), children first:
                 favourites, comments, client sessions, download records + jobs, upload sessions,
                 media, albums, clients, the studio login, studio settings, the studio row;
                 the platform storage ledger gets back the studio's used + reserved bytes
              Then, after the commit, from object storage (R2):
                 every original and thumbnail the studio's rows point to (each key is checked to belong
                 to THIS studio first), its thumbnail folders, then a sweep of the studio's own folder
                 (studios/<name>-<id>/ - also catches unreferenced leftovers and the logo), and any ZIP
                 temp files of its download jobs
        ▼
 audit: studio_deleted {name, studio_id}  (B also records data_deleted, clients, albums, media, bytes,
        objects_deleted, storage_failures). Earlier audit rows of that studio are kept; their studio link becomes empty.
```

What B means for people: the studio's admin can no longer sign in, and its **clients lose their galleries** (the gallery link and password stop working). Nothing is recoverable afterwards - take a backup first if there is any chance the studio's photographs are needed.

If object storage is unreachable during B, the database is still cleaned (the studio is gone) and the response/toast reports how many objects could not be removed (`storage_failures`); list and remove the leftovers later with `python -m app.reconcile_orphans` (dry run first, then `--apply`). Another studio's rows and files are never touched.

### 5.3 Change a studio's storage quota

```
Quota card → number + unit → Save                     PUT /studios/{id}/quota
   rule: new quota >= used + reserved   (else 409 QUOTA_BELOW_USAGE)
   max:  100 TB per studio
   audit: studio_quota_changed {old, new}
```

How the quota is enforced at upload time (the numbers on the Storage card):

```
 start upload      reserve(size)      studio.reserved += size   AND   platform.reserved += size
                   fails with 413 STUDIO_QUOTA_EXCEEDED  or  PLATFORM_CAPACITY_EXCEEDED if either ceiling would be crossed
 file verified     commit             reserved -= size ;  used += real stored size
 failed/cancelled  release            reserved -= size
 media deleted     decrease_used      used -= size
```

`used + reserved` can never exceed the studio quota, and the platform total can never exceed the platform capacity.

### 5.4 Disable / enable the studio login

```
Studio login account → Disable login  ──►  confirm  ──►  POST .../admins/{id}/disable
   status = disabled, session_version + 1 (signed out at once)           audit: studio_admin_disabled
   the studio's clients, albums, photos, quota and the clients' gallery access are untouched
Studio login account → Enable login   ──►  confirm  ──►  POST .../admins/{id}/enable      audit: studio_admin_enabled
```

Every authenticated studio request re-reads the login's status and `session_version`, so disabling, changing the email or resetting the password invalidates the existing session on its very next request.

### 5.5 Reset the studio login's password

```
Actions ▾ → Reset password → Generate (or type) → Update password
   POST .../admins/{id}/reset-password   body: {new_password}  (omit → server generates one and returns it once)
   password hashed, session_version + 1 → every old session and cookie of that user stops working
   audit: studio_admin_password_reset   (only the fact that it happened)
```

### 5.6 Studio logo

```
Studio details → choose image → Upload     POST /studios/{id}/logo    (replace the same way)
   accepted: PNG / JPEG / WebP / GIF, max 5 MB, max 50 megapixels
   re-encoded to a 512 px PNG, stored at  studios/{name}-{id}/branding/logo-{hash}.png
   served publicly at  /api/studios/{id}/logo?v={hash}
Remove                                     DELETE /studios/{id}/logo
   audit: studio_logo_updated / studio_logo_removed
```

---

## 6. Data behind the console

### 6.1 `studios`

| Field | Meaning |
|---|---|
| `id`, `name` | Identity. The name can be renamed freely |
| `contact_email`, `contact_phone` | Shown in the studios list (Contact column) |
| `logo_url`, `brand_color` | Branding (logo is a stored image; colour must be `#rrggbb`; a manual `logo_url` must be `https://`) |
| `status` | `active` or `suspended` |
| `quota_bytes` | Hard ceiling for used + reserved (default 10 GB, max 100 TB) |
| `used_bytes` | Verified stored media |
| `reserved_bytes` | Promised to in-flight uploads |
| `storage_prefix` | R2 folder, e.g. `studios/acme-photo-1`, fixed at creation; empty on legacy studios (they use `studios/{id}`) |
| `created_at`, `updated_at` | Timestamps |

`used_bytes` / `reserved_bytes` change only through `quota_service` (atomic conditional updates), never by editing the row.

### 6.2 `admins` (both roles)

| Field | Meaning |
|---|---|
| `name`, `email` | Email is unique across the platform and stored lower-case |
| `password_hash` | Argon2 — the password itself is never stored |
| `role` | `super_admin` (no studio) or `studio_admin` |
| `studio_id` | The one studio a studio admin belongs to (empty for super admins) |
| `status` | `active` or `disabled` |
| `session_version` | Increases on password change/reset/disable/email change; old cookies stop working |

### 6.3 `audit_logs`

Who (`user_type`, `user_id`, `actor_role`) did what (`action`) to which studio (`studio_id`) and resource
(`resource_type`, `resource_id`), from which IP, when, plus small non-sensitive `event_metadata`.

### 6.4 `platform_storage` (one row)

Platform-wide `used_bytes` and `reserved_bytes`. Capacity comes from the `PLATFORM_CAPACITY_BYTES` setting (default 1 TB).

---

## 7. API reference (all under `/api/super-admin`, super admin only)

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /stats` | Dashboard numbers | studios (total/active/suspended), totals, storage, unmapped legacy rows |
| `GET /stats/trends` | Dashboard charts | `days` = 7, 30 or 90 (anything else → 30). Daily new studios/clients/albums/files, bytes uploaded, downloads and bytes downloaded, totals for the range and the period before, photo/video totals, 5 most active studios |
| `GET /studios` | List studios | `page`, `limit` (≤200), `status`, `search` (name) |
| `POST /studios` | Create studio + its one login | Returns `temporary_password` once if generated; the logo is uploaded afterwards with `POST /studios/{id}/logo` |
| `GET /studios/{id}` | Studio detail | Includes counts |
| `PUT /studios/{id}` | Edit details | name, contact email/phone, logo URL, brand colour |
| `POST /studios/{id}/logo` · `DELETE /studios/{id}/logo` | Upload / remove logo | See §5.6 |
| `POST /studios/{id}/suspend` · `POST /studios/{id}/reactivate` | Change status | Optional `reason` |
| `DELETE /studios/{id}` | Delete a suspended studio; its login goes with it. Empty studios only, unless `?delete_data=true&confirm_name=<exact name>` is given: then **all of its data** (clients, albums, media rows and stored files, comments, favourites, download history) is deleted too | `409 STUDIO_NOT_SUSPENDED` / `STUDIO_NOT_EMPTY` / `400 CONFIRMATION_MISMATCH` |
| `PUT /studios/{id}/quota` | Set quota | `409 QUOTA_BELOW_USAGE` |
| `GET /studios/{id}/usage` | Quota numbers | used / reserved / remaining |
| `GET /studios/{id}/admins` | The studio's login (a list with 0 or 1 item) | |
| `POST /studios/{id}/admins` | **Recovery only**: give a studio that has **no** login its one login | `409 STUDIO_USER_LIMIT` when it already has one (so a second login can never be created), `409 ADMIN_EMAIL_EXISTS` |
| `PUT /studios/{id}/admins/{admin_id}` | Edit name and/or email (either field alone is fine) | Email change signs the login out |
| `POST /studios/{id}/admins/{admin_id}/disable` · `.../enable` | Disable / re-enable | Disable signs the user out |
| `POST /studios/{id}/admins/{admin_id}/reset-password` | Reset password | Body optional |
| `GET /audit-logs` | Audit trail | `studio_id`, `action`, `from`, `to`, `tz_offset` (viewer's minutes east of UTC, so `from`/`to` are local days; default 0 = UTC), `category` (sign_in, studios, logins, storage, content, problems), `actor` (super_admin, studio_admin, client), `search`, `sort` (newest, oldest), `page`, `limit` (≤200). The response also carries a `summary` (events and failed sign-ins in 24 h, total) |
| `GET /audit-logs/export` | CSV of the entries matching the same filters | Newest first, max 10,000 rows; audited as `audit_log_exported` |
| `POST /change-password` | Change your own password | Needs the current password |
| `GET /account` · `PUT /account` | Your account | name, email, company name, contact number, logo, role, created, last 10 sign-in attempts · edit name / email / company name / contact number (`current_password` required for a new email) |
| `POST /account/logo` · `DELETE /account/logo` | Company logo | Upload (multipart field `file`) / remove the logo shown in the sidebar |
| `POST /sign-out-others` | Sign out other devices | Bumps the session version and re-issues this browser's cookie |

Responses use one envelope: `{ "success": true, "data": … }` or `{ "success": false, "error": { "code", "message" } }`.

---

## 8. Audit action catalogue

| Action | Written when |
|---|---|
| `studio_created` | A studio is created |
| `studio_updated` | Studio details edited (metadata lists which fields) |
| `studio_logo_updated` / `studio_logo_removed` | Logo uploaded or replaced / removed |
| `super_admin_logo_updated` / `super_admin_logo_removed` | The super admin's company logo uploaded or replaced / removed |
| `studio_suspended` / `studio_reactivated` | Status changed (suspend stores the reason) |
| `studio_deleted` | An empty studio was deleted (name and id in the details) |
| `studio_quota_changed` | Quota changed (old and new value) |
| `audit_log_exported` | The audit log was exported to CSV (row count and the filters used) |
| `storage_counters_repaired` | Storage counters were repaired from the Storage page (how many studios) |
| `studio_admin_created` | User added to a studio |
| `studio_admin_updated` | User's name or email edited |
| `studio_admin_disabled` / `studio_admin_enabled` | User disabled / re-enabled |
| `studio_admin_deleted` | User deleted (email, name, whether the contact email was cleared) |
| `studio_admin_password_reset` | Password reset by the super admin |
| `super_admin_password_changed` | The super admin changed their own password |
| `super_admin_account_updated` | The super admin edited their own name / email (field names only) |
| `super_admin_signed_out_other_devices` | The super admin signed out their other devices |
| `admin_login` / `admin_login_failed` | Any admin sign-in succeeded / failed |
| `media_uploaded`, `media_upload_failed`, `media_deleted`, `album_deleted`, `client_deleted` | Studio activity, visible to the super admin for oversight |

The audit filter accepts any action text. The suggestion list in the console does not yet include the four newer
`studio_admin_updated / disabled / enabled / deleted` actions, but typing them works.

---

## 9. Validation and limits at a glance

| Item | Rule |
|---|---|
| Studio / user name | 1–255 characters, not blank |
| Email | Valid address; user emails unique platform-wide |
| Password (typed or reset) | 4–128 characters. Generated ones are random |
| Quota | > 0 and ≤ 100 TB; never below used + reserved |
| Brand colour | `#rrggbb` |
| Logo URL (manual) | `https://` only |
| Logo upload | PNG / JPEG / WebP / GIF, ≤ 5 MB, ≤ 50 MP, stored as 512 px PNG |
| Suspend reason | ≤ 300 characters |
| Lists | Studios 20/page in the console (API max 200); audit log 50/page |

---

## 10. Error codes you may see

| Code | Meaning |
|---|---|
| `SUPER_ADMIN_REQUIRED` (403) | A non-super-admin called a console route |
| `ADMIN_NOT_FOUND` (404) | The login is not in that studio (or is the super admin) |
| `ADMIN_EMAIL_EXISTS` (409) | The email is already used by another account |
| `STUDIO_USER_LIMIT` (409) | The studio already has its one login — edit it, change its email or reset its password instead |
| `QUOTA_BELOW_USAGE` (409) | New quota is lower than what the studio already holds |
| `STUDIO_SUSPENDED` (403) | A change was attempted in a suspended studio |
| `STUDIO_NOT_SUSPENDED` (409) | Delete was attempted on a studio that is still active |
| `STUDIO_NOT_EMPTY` (409) | Plain delete was attempted while the studio still holds clients, albums or files (use delete-with-data) |
| `CONFIRMATION_MISMATCH` (400) | Delete-with-data was sent without the studio's exact name |
| `STUDIO_QUOTA_EXCEEDED` (413) | An upload would pass the studio quota |
| `PLATFORM_CAPACITY_EXCEEDED` | An upload would pass the whole platform's capacity |
| `INVALID_STATUS`, `INVALID_DATE_RANGE` (400) | Bad filter value |
| `INVALID_CURRENT_PASSWORD` (400) | Wrong current password when changing your own |

---

## 11. Command-line tools (run on the server, not in the console)

| Command | Use |
|---|---|
| `python -m app.create_super_admin` | Create a super admin |
| `python -m app.legacy_to_studio` | Move pre-multi-studio data into a studio (dry run by default, `--apply` to write) |
| `python -m app.consolidate_studio_logins` | One-time cleanup for data created before the one-login rule: reports studios that have more than one login (default, changes nothing); `--keep STUDIO_ID:ADMIN_ID` (or `--keep-oldest` / `--keep-newest`) with `--apply` keeps one login per studio, **disables, signs out and detaches** the others (nothing is deleted unless you pass `--action delete --yes`), then creates the database rule. See `MULTI_STUDIO.md` |
| `python -m app.reconcile_quota` | Report drift in used/reserved (default); `--apply` repairs the counters from the real rows; `--studio-id N` limits it to one studio |
| `python -m app.reconcile_orphans` | Dry run lists stored objects with no database row; `--apply` deletes the confirmed orphans |
| `python scripts/check_r2.py` (run from `backend/`) | Check the R2 credentials and bucket; `--read-only` never writes |

---

## 12. What the super admin cannot do (by design)

* Open a studio's clients, albums or photos, or download them.
* Read any password — passwords are stored only as Argon2 hashes; only a reset (new password) is possible.
* Delete a studio that is still active. A suspended studio can be deleted — empty, or with all of its data after typing its name — taking its login with it (see §5.2b).
* Delete or disable another super admin through a studio's Login menu (the console only addresses studio logins).
* Add a second login to a studio, or delete a studio's login on its own (one studio = one login; remove the studio to remove its login).
