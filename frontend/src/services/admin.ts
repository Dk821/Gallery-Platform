import { api, API_BASE_URL, DownloadJob, MediaItem, Page } from "./api";

export interface ClientListItem {
  id: number;
  client_uuid: string;
  client_name: string;
  status: "active" | "disabled";
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
  createClient: (clientName: string, password: string, downloadPassword?: string) =>
    api.post<ClientDetail>("/admin/clients", {
      client_name: clientName,
      password,
      ...(downloadPassword ? { download_password: downloadPassword } : {}),
    }),

  changePassword: (clientId: number, password: string) =>
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

  listAlbums: (page = 1, limit = 50) =>
    api.get<Page<AlbumItem>>(`/admin/albums?page=${page}&limit=${limit}`),

  getAlbum: (albumId: number) => api.get<AlbumItem>(`/admin/albums/${albumId}`),

  createAlbum: (clientId: number, albumName: string, description?: string) =>
    api.post<AlbumItem>("/admin/albums", { client_id: clientId, album_name: albumName, description }),

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

  listAlbumMedia: (albumId: number, page = 1, limit = 50, search?: string) => {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (search) params.set("search", search);
    return api.get<Page<MediaItem>>(`/admin/albums/${albumId}/media?${params.toString()}`);
  },

  // Backs "Select All" so it selects every matching item across all pages,
  // not just what's currently loaded in the grid.
  getAlbumMediaSelectionSummary: (albumId: number, search?: string) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    const qs = params.toString();
    return api.get<{ ids: number[]; total_count: number; total_bytes: number }>(
      `/admin/albums/${albumId}/media/selection-summary${qs ? `?${qs}` : ""}`
    );
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

  // XMLHttpRequest instead of fetch here specifically because fetch has no
  // upload progress event - XHR's upload.onprogress is what drives the
  // per-file progress bar on the Uploads page.
  uploadMedia: (
    albumId: number,
    file: File,
    uploadId: string,
    onProgress: (percent: number) => void
  ): { promise: Promise<MediaItem>; cancel: () => void } => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("album_id", String(albumId));
    formData.append("file", file);
    // Idempotency key (Section 4): the caller passes the SAME uploadId on
    // every retry of the same logical upload, so a browser retry after a
    // lost response never creates a duplicate Drive file or Media record.
    formData.append("upload_id", uploadId);

    const promise = new Promise<MediaItem>((resolve, reject) => {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
      xhr.addEventListener("load", () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300 && body.success) {
            resolve(body.data as MediaItem);
          } else {
            reject(new Error(body.error?.message ?? "Upload failed."));
          }
        } catch {
          reject(new Error("Upload failed."));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("Network error during upload.")));
      xhr.addEventListener("abort", () => reject(new Error("Upload cancelled.")));

      xhr.open("POST", `${API_BASE_URL}/api/admin/media/upload`);
      xhr.withCredentials = true;
      xhr.send(formData);
    });

    return { promise, cancel: () => xhr.abort() };
  },

  // Pre-creates the UploadSession (status="queued") BEFORE the actual file
  // upload so the status poll never 404s. Large files take a while to
  // buffer on the server, and previously the frontend started polling
  // before the session row existed.
  createUploadSession: (albumId: number, uploadId: string, filename: string, fileSize: number) =>
    api.post<{
      upload_id: string;
      status: "queued" | "uploading" | "completed" | "failed" | "cancelled";
      total_bytes: number;
      bytes_uploaded: number;
      percentage: number;
      media_id: number | null;
      error_code: string | null;
      error_message: string | null;
    }>("/admin/media/upload-session", { album_id: albumId, upload_id: uploadId, filename, file_size: fileSize }),

  // Real, Drive-side transfer progress (Section 8) - distinct from the
  // browser's own upload.progress event, which only reflects bytes sent
  // to OUR server, not bytes actually confirmed by Google Drive. Polled
  // by the UI once the browser has finished sending the file, while the
  // server is still relaying it to storage.
  getUploadStatus: (uploadId: string) =>
    api.get<{
      upload_id: string;
      status: "queued" | "uploading" | "completed" | "failed" | "cancelled";
      total_bytes: number;
      bytes_uploaded: number;
      percentage: number;
      media_id: number | null;
      error_code: string | null;
      error_message: string | null;
    }>(`/admin/media/upload-status/${uploadId}`),

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
