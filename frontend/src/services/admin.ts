import { api, API_BASE_URL, DownloadJob, MediaItem, Page } from "./api";

export interface ClientListItem {
  id: number;
  client_uuid: string;
  client_name: string;
  status: "active" | "disabled";
  has_password: boolean;
  has_download_password: boolean;
  created_at: string;
  album_count: number;
  media_count: number;
}

export interface ClientDetail {
  id: number;
  client_uuid: string;
  client_name: string;
  status: "active" | "disabled";
  has_password: boolean;
  has_download_password: boolean;
  created_at: string;
  last_login_at: string | null;
  gallery_url_path: string;
}

export interface DashboardSummary {
  total_clients: number;
  active_clients: number;
  total_albums: number;
  total_photos: number;
  total_videos: number;
  storage_used_bytes: number;
  downloads_summary: DownloadSummary;
  recent_clients: {
    id: number;
    client_uuid: string;
    client_name: string;
    status: string;
    created_at: string;
  }[];
}

export interface DownloadSummary {
  total_downloads: number;
  total_transferred_bytes: number;
  recent_24h: number;
}

export interface AlbumDownloadStat {
  album_id: number;
  album_name: string;
  client_name: string;
  download_count: number;
  total_bytes: number;
  last_downloaded: string | null;
}

export interface DownloadHistoryEvent {
  downloaded_at: string;
  download_type: "all" | "selected";
  file_count: number;
  total_bytes: number;
  album_name: string;
  client_name: string;
  status: string;
}

export interface DownloadAnalytics {
  summary: DownloadSummary;
  albums: AlbumDownloadStat[];
  history: DownloadHistoryEvent[];
}

export type ActivityType = "upload" | "download" | "client" | "album";

export interface ActivityItem {
  id: string;
  type: ActivityType;
  title: string;
  description: string;
  actor: string;
  occurred_at: string;
  meta: {
    album_name?: string | null;
    client_name?: string | null;
    file_count?: number;
    total_bytes?: number;
    download_type?: "all" | "selected";
  };
}

export interface ActivityResponse {
  items: ActivityItem[];
  total: number;
  limit: number;
}

export interface AlbumItem {
  id: number;
  album_uuid: string;
  client_id: number;
  album_name: string;
  description: string | null;
  status: "active" | "disabled";
  expires_at: string | null;
  created_at: string;
  media_count: number;
  // Aggregated server-side alongside media_count (see album_service
  // .list_albums_for_admin) - the client gallery page renders these instead
  // of counting the media rows it happened to load.
  photo_count: number;
  video_count: number;
  total_bytes: number;
}

// Re-exported so existing call sites (e.g. Uploads.tsx) that import
// MediaItem from "./admin" keep working unchanged - the actual definition
// lives in api.ts, shared with gallery.ts.
export type { MediaItem };

export interface MediaUpdatePayload {
  file_name?: string;
  title?: string;
  description?: string;
}

// Shared shape for both GET /upload-status and (as a base) POST
// /upload-session's response - mirrors the backend's UploadStatusResponse
// exactly (app/schemas/media.py).
export interface UploadSessionStatus {
  upload_id: string;
  status: "queued" | "uploading" | "completed" | "failed" | "cancelled";
  total_bytes: number;
  bytes_uploaded: number;
  percentage: number;
  media_id: number | null;
  error_code: string | null;
  error_message: string | null;
}

// Admin album filter: which of the client's wishlist state to show.
export type WishlistFilter = "all" | "wishlisted" | "not_wishlisted";

export interface WishlistCounts {
  all: number;
  wishlisted: number;
  not_wishlisted: number;
}

export const adminService = {
  getDashboard: () => api.get<DashboardSummary>("/admin/dashboard"),

  getDownloadAnalytics: () => api.get<DownloadAnalytics>("/admin/downloads/analytics"),

  getActivity: (params: {
    search?: string;
    type?: ActivityType | "all";
    from?: string;
    to?: string;
    limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params.search) qs.set("search", params.search);
    if (params.type && params.type !== "all") qs.set("type", params.type);
    if (params.from) qs.set("from", params.from);
    if (params.to) qs.set("to", params.to);
    if (params.limit) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return api.get<ActivityResponse>(`/admin/activity${query ? `?${query}` : ""}`);
  },

  listClients: (page = 1, limit = 50) =>
    api.get<Page<ClientListItem>>(`/admin/clients?page=${page}&limit=${limit}`),
  createClient: (clientName: string, password?: string, downloadPassword?: string) =>
    api.post<ClientDetail>("/admin/clients", {
      client_name: clientName,
      // Gallery password is optional - omit it entirely when blank so the
      // gallery is created without password protection.
      ...(password ? { password } : {}),
      ...(downloadPassword ? { download_password: downloadPassword } : {}),
    }),

  // password: null removes the gallery password entirely (gallery becomes
  // passwordless), mirroring changeDownloadPassword.
  changePassword: (clientId: number, password: string | null) =>
    api.post<ClientDetail>(`/admin/clients/${clientId}/change-password`, { password }),

  changeDownloadPassword: (clientId: number, password: string | null) =>
    api.post<ClientDetail>(`/admin/clients/${clientId}/change-download-password`, { password }),

  getClientPasswords: (clientId: number) =>
    api.get<{ gallery_password: string | null; download_password: string | null }>(
      `/admin/clients/${clientId}/passwords`
    ),

  getClientDetail: (clientId: number) =>
    api.get<ClientDetail>(`/admin/clients/${clientId}`),

  disableClient: (clientId: number) => api.post<ClientDetail>(`/admin/clients/${clientId}/disable`),

  enableClient: (clientId: number) => api.post<ClientDetail>(`/admin/clients/${clientId}/enable`),

  updateClient: (clientId: number, payload: { client_name?: string }) =>
    api.patch<ClientDetail>(`/admin/clients/${clientId}`, payload),

  removeClient: (clientId: number) => api.delete<null>(`/admin/clients/${clientId}`),

  listAlbums: (page = 1, limit = 50, clientId?: number) => {
    const qs = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (clientId !== undefined && clientId !== null) qs.set("client_id", String(clientId));
    return api.get<Page<AlbumItem>>(`/admin/albums?${qs.toString()}`);
  },

  getAlbum: (albumId: number) => api.get<AlbumItem>(`/admin/albums/${albumId}`),

  createAlbum: (clientId: number, albumName: string, description?: string, expiresAt?: string | null) =>
    api.post<AlbumItem>("/admin/albums", {
      client_id: clientId,
      album_name: albumName,
      description,
      ...(expiresAt ? { expires_at: expiresAt } : {}),
    }),

  // expiresAt: pass an ISO string to set/change it, null to clear it, or
  // omit the key entirely (don't include expiresAt in the call) to leave
  // it untouched - matches the three-state PATCH semantics the backend
  // expects (see AlbumUpdateRequest).
  updateAlbum: (
    albumId: number,
    updates: { album_name?: string; description?: string; expires_at?: string | null }
  ) => api.put<AlbumItem>(`/admin/albums/${albumId}`, updates),

  removeAlbum: (albumId: number) => api.delete<null>(`/admin/albums/${albumId}`),

  // --- Album media management (admin) ---

  listAlbumMedia: (albumId: number, page = 1, limit = 50, search?: string, wishlist: WishlistFilter = "all") => {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (search) params.set("search", search);
    if (wishlist !== "all") params.set("wishlist", wishlist);
    return api.get<Page<MediaItem>>(`/admin/albums/${albumId}/media?${params.toString()}`);
  },

  // Backs "Select All" so it selects every matching item across all pages,
  // not just what's currently loaded in the grid. Takes the SAME wishlist
  // filter as the grid: Select All feeds bulk delete/move/download, so under
  // the Wishlist tab it must select only the wishlisted items.
  getAlbumMediaSelectionSummary: (albumId: number, search?: string, wishlist: WishlistFilter = "all") => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (wishlist !== "all") params.set("wishlist", wishlist);
    const qs = params.toString();
    return api.get<{ ids: number[]; total_count: number; total_bytes: number }>(
      `/admin/albums/${albumId}/media/selection-summary${qs ? `?${qs}` : ""}`
    );
  },

  // "All 250 / Wishlist 38 / Not wishlisted 212" - one aggregate query.
  getAlbumWishlistCounts: (albumId: number, search?: string) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    const qs = params.toString();
    return api.get<WishlistCounts>(`/admin/albums/${albumId}/media/wishlist-counts${qs ? `?${qs}` : ""}`);
  },

  // Everything a client has wishlisted (read-only for admins), optionally
  // narrowed to one of that client's albums.
  getClientWishlist: (clientId: number, page = 1, limit = 50, albumId?: number) => {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (albumId !== undefined) params.set("album_id", String(albumId));
    return api.get<Page<MediaItem>>(`/admin/clients/${clientId}/wishlist?${params.toString()}`);
  },

  getMedia: (mediaId: number) => api.get<MediaItem>(`/admin/media/${mediaId}`),

  updateMedia: (mediaId: number, payload: MediaUpdatePayload) =>
    api.patch<MediaItem>(`/admin/media/${mediaId}`, payload),

  moveMedia: (mediaId: number, targetAlbumId: number) =>
    api.post<MediaItem>(`/admin/media/${mediaId}/move`, { target_album_id: targetAlbumId }),

  removeMedia: (mediaId: number) => api.delete<null>(`/admin/media/${mediaId}`),

  bulkDeleteMedia: (mediaIds: number[]) =>
    api.post<BulkResult>("/admin/media/bulk-delete", { media_ids: mediaIds }),

  bulkMoveMedia: (mediaIds: number[], targetAlbumId: number) =>
    api.post<BulkMoveResult>("/admin/media/bulk-move", {
      media_ids: mediaIds,
      target_album_id: targetAlbumId,
    }),

  adminThumbnailUrl: (mediaId: number) => `${API_BASE_URL}/api/admin/media/${mediaId}/thumbnail`,
  adminViewUrl: (mediaId: number) => `${API_BASE_URL}/api/admin/media/${mediaId}/view`,
  adminDownloadUrl: (mediaId: number) => `${API_BASE_URL}/api/admin/media/${mediaId}/download`,

  // ZIP background-job downloads (admin-initiated bulk ZIP, Part 1) - same
  // underlying job system the client uses, reached via admin auth instead.
  createAlbumDownloadJob: (albumId: number, mediaIds?: number[]) =>
    api.post<DownloadJob>(`/admin/albums/${albumId}/download-jobs`, mediaIds ? { media_ids: mediaIds } : {}),

  getDownloadJobStatus: (jobId: number) => api.get<DownloadJob>(`/admin/download-jobs/${jobId}`),

  cancelDownloadJob: (jobId: number) => api.post<DownloadJob>(`/admin/download-jobs/${jobId}/cancel`),

  downloadJobFileUrl: (jobId: number) => `${API_BASE_URL}/api/admin/download-jobs/${jobId}/file`,

  // Browser -> Google Drive DIRECT upload (Section: architecture change).
  // This server is never in the byte-transfer path for the main file -
  // startUploadSession() only exchanges metadata and gets back a Drive
  // resumable session URL; uploadToDrive() PUTs the actual bytes straight
  // to Google; completeUpload() tells our backend the transfer finished
  // so it can confirm with Drive and create the Media record.

  // Step 1: ask the backend to reserve the upload-session row (Section 4
  // idempotency ledger) and open a Google Drive resumable-upload session.
  // upload_url is null only on an idempotent replay of an
  // already-completed upload (media_id will be set instead - nothing left
  // to send).
  createUploadSession: (albumId: number, uploadId: string, filename: string, fileSize: number) =>
    api.post<UploadSessionStatus & { upload_url: string | null }>("/admin/media/upload-session", {
      album_id: albumId,
      upload_id: uploadId,
      filename,
      file_size: fileSize,
    }),

  // Step 2: PUT the file directly to the Drive resumable session URL from
  // startUploadSession/createUploadSession above. This is a request to
  // googleapis.com, NOT to our own API - no credentials, no API_BASE_URL,
  // and XMLHttpRequest (not fetch) specifically because fetch has no
  // upload-progress event, which is what drives the per-file progress bar
  // on the Uploads page. The session URL itself is the (short-lived,
  // single-use) credential for this request - Drive's resumable-upload
  // protocol doesn't need an Authorization header replayed against it.
  uploadToDrive: (
    uploadUrl: string,
    file: File,
    onProgress: (percent: number) => void
  ): { promise: Promise<{ driveFileId: string; size: number; mimeType: string }>; cancel: () => void } => {
    const xhr = new XMLHttpRequest();

    const promise = new Promise<{ driveFileId: string; size: number; mimeType: string }>((resolve, reject) => {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
      xhr.addEventListener("load", () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error(`Upload to Google Drive failed (status ${xhr.status}).`));
          return;
        }
        try {
          const body = JSON.parse(xhr.responseText);
          resolve({
            driveFileId: body.id as string,
            size: Number(body.size ?? file.size),
            mimeType: (body.mimeType as string) ?? file.type,
          });
        } catch {
          reject(new Error("Upload to Google Drive succeeded but the response could not be read."));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("Network error while uploading to Google Drive.")));
      xhr.addEventListener("abort", () => reject(new Error("Upload cancelled.")));

      xhr.open("PUT", uploadUrl);
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
      xhr.send(file);
    });

    return { promise, cancel: () => xhr.abort() };
  },

  // Step 2b (best-effort): send the small thumbnail the browser produced
  // locally - a video poster frame (utils/videoPoster.ts) or a downscaled
  // photo thumb (utils/photoThumbnail.ts) - AFTER the direct PUT to Drive
  // has finished and BEFORE completeUpload(). The original file is never
  // sent to our server, and completeUpload() no longer has to download it
  // back from Drive to make a thumbnail - it just links the thumbnail
  // recorded here (normalized to WebP server-side). Callers must treat any
  // failure as non-fatal: without a thumbnail the item simply shows a
  // placeholder tile in the gallery.
  uploadThumbnail: (uploadId: string, thumbnail: Blob) => {
    const form = new FormData();
    form.append("file", thumbnail, "thumb.webp");
    return api.postForm<{ upload_id: string; has_thumbnail: boolean }>(
      `/admin/media/upload-session/${uploadId}/thumbnail`,
      form
    );
  },

  // Step 3: tell the backend the direct-to-Drive transfer finished, so it
  // can re-confirm the file WITH DRIVE ITSELF (never trusting these
  // reported values for the actual Media record - see
  // complete_direct_upload on the backend) and create the Media row.
  completeUpload: (uploadId: string, driveFileId: string, reportedSize: number, reportedMimeType: string) =>
    api.post<MediaItem>("/admin/media/upload-complete", {
      upload_id: uploadId,
      drive_file_id: driveFileId,
      reported_size: reportedSize,
      reported_mime_type: reportedMimeType,
    }),

  // Best-effort, throttled progress ping while uploadToDrive() is running
  // (Section 8) - purely cosmetic, lets OTHER views of this admin's
  // upload list (e.g. a second tab, or this page after a refresh) see
  // live-ish progress even though this server isn't relaying the bytes
  // itself anymore. Callers should throttle this to roughly once a
  // second and swallow failures (a missed ping is never fatal).
  reportUploadProgress: (uploadId: string, bytesUploaded: number) =>
    api.post<UploadSessionStatus>(`/admin/media/upload-progress/${uploadId}`, { bytes_uploaded: bytesUploaded }),

  // Real, server-confirmed status (Section 8) - reflects what the backend
  // actually knows (queued/uploading/completed/failed), not just what the
  // browser has reported via reportUploadProgress above. Polled by the UI
  // as the authoritative source of truth, e.g. after a page refresh or
  // once completeUpload() has been called.
  getUploadStatus: (uploadId: string) => api.get<UploadSessionStatus>(`/admin/media/upload-status/${uploadId}`),

  // Tells the backend a direct-to-Drive attempt failed/was cancelled in
  // the browser, so the SAME upload_id can be retried immediately rather
  // than being rejected as "already in progress" - this server has no
  // other way to learn that a direct browser<->Drive transfer failed.
  // Best-effort: callers should swallow failures from this call itself.
  abandonUploadSession: (uploadId: string) =>
    api.post<null>(`/admin/media/upload-session/${uploadId}/abandon`),

  // Backs the Uploads page's refresh-recovery: the server persists every
  // upload session (idempotency ledger), so after a page reload the page
  // can rebuild its in-memory list - including in-flight and just-finished
  // transfers - instead of losing track of them entirely.
  listUploadSessions: (limit = 50) =>
    api.get<UploadSessionListItem[]>(`/admin/media/upload-sessions?limit=${limit}`),

  getStorageOverview: (days: 7 | 30 | 90 = 30) =>
    api.get<StorageOverview>(`/admin/storage?days=${days}`),

  getSettings: () => api.get<SettingsResponse>("/admin/settings"),

  updateStudioProfile: (studioName: string, contactEmail: string) =>
    api.put<StudioSettings>("/admin/settings/profile", {
      studio_name: studioName.trim() ? studioName : null,
      contact_email: contactEmail.trim() ? contactEmail : null,
    }),

  updateSecurityPolicy: (minClientPasswordLength: number, downloadLinkTtlHours: number) =>
    api.put<StudioSettings>("/admin/settings/security", {
      min_client_password_length: minClientPasswordLength,
      download_link_ttl_hours: downloadLinkTtlHours,
    }),

  changeAdminPassword: (currentPassword: string, newPassword: string) =>
    api.post<void>("/admin/settings/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),
};

export interface BulkResult {
  deleted: number[];
  failed: { id: number; code: string; message: string }[];
}

export interface BulkMoveResult {
  moved: number[];
  failed: { id: number; code: string; message: string }[];
}

export interface StorageOverview {
  our_metadata: {
    total_files: number;
    total_photos: number;
    total_videos: number;
    total_bytes_tracked: number;
  };
  drive_quota:
    | { available: false }
    | { available: true; usage_bytes: number; limit_bytes: number | null };
  vps_disk: {
    path: string;
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    reserved_bytes: number;
    min_free_bytes: number;
    effective_available_bytes: number;
    percent_used: number;
  };
  daily_transfer: {
    date: string;
    upload_bytes: number;
    upload_count: number;
    download_bytes: number;
    download_count: number;
  }[];
  storage_by_client: {
    client_id: number;
    client_name: string;
    total_bytes: number;
    file_count: number;
  }[];
  storage_by_file_type: {
    file_type: "photo" | "video";
    total_bytes: number;
    file_count: number;
  }[];
  upload_reliability: {
    by_status: Record<string, number>;
    recent_window_days: number;
    recent_total: number;
    recent_completed: number;
    recent_success_rate_percent: number | null;
  };
  largest_files: {
    media_id: number;
    file_name: string;
    file_type: "photo" | "video";
    file_size: number;
    uploaded_at: string;
    album_name: string;
    client_name: string;
  }[];
  orphan_candidate_count: number;
}

export interface UploadSessionListItem {
  upload_id: string;
  filename: string;
  album_id: number;
  album_name: string;
  client_name: string;
  status: "queued" | "uploading" | "completed" | "failed" | "cancelled";
  total_bytes: number;
  bytes_uploaded: number;
  percentage: number;
  media_id: number | null;
  error_code: string | null;
  error_message: string | null;
}

export interface StudioSettings {
  studio_name: string | null;
  contact_email: string | null;
  min_client_password_length: number;
  download_link_ttl_hours: number;
  updated_at: string;
}

export interface SettingsResponse {
  studio: StudioSettings;
  admin: { id: number; name: string; email: string };
}
