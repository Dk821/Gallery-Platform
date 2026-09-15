import { api, API_BASE_URL, DownloadJob, MediaItem, Page } from "./api";

export interface GalleryInfo {
  client_name: string;
  client_uuid: string;
  has_download_password: boolean;
}

export interface GalleryAlbum {
  id: number;
  album_uuid: string;
  client_id: number;
  album_name: string;
  description: string | null;
  status: string;
  expires_at: string | null;
  created_at: string;
  media_count: number;
}

// Same shape as MediaItem (both are served by the backend's shared
// media_to_response() presenter) - re-exported under this name so existing
// imports across the client gallery pages/components don't need to change.
export type GalleryMedia = MediaItem;

export interface SelectionSummary {
  ids: number[];
  total_count: number;
  total_bytes: number;
}

export const galleryService = {
  getGallery: () => api.get<GalleryInfo>("/client/gallery"),

  listAlbums: (page = 1, limit = 50) =>
    api.get<Page<GalleryAlbum>>(`/client/albums?page=${page}&limit=${limit}`),

  getAlbum: (albumId: number) => api.get<GalleryAlbum>(`/client/albums/${albumId}`),

  listMedia: (albumId: number, page = 1, limit = 50, search?: string) => {
    const params = new URLSearchParams({
      album_id: String(albumId),
      page: String(page),
      limit: String(limit),
    });
    if (search) params.set("search", search);
    return api.get<Page<GalleryMedia>>(`/client/media?${params.toString()}`);
  },

  // Backs "Select All" (correct across pagination) and the "~1.4 GB" size
  // estimate - returns every matching id + total bytes without pulling
  // full metadata for anything outside the current page.
  getSelectionSummary: (albumId: number, search?: string) => {
    const params = new URLSearchParams({ album_id: String(albumId) });
    if (search) params.set("search", search);
    return api.get<SelectionSummary>(`/client/media/selection-summary?${params.toString()}`);
  },

  thumbnailUrl: (mediaId: number) => `${API_BASE_URL}/api/client/media/${mediaId}/thumbnail`,
  viewUrl: (mediaId: number) => `${API_BASE_URL}/api/client/media/${mediaId}/view`,
  downloadUrl: (mediaId: number) => `${API_BASE_URL}/api/client/media/${mediaId}/download`,

  // ZIP background-job downloads (Parts 7-9). Omit mediaIds for "the whole
  // album"; pass a list for "just these selected items."
  createDownloadJob: (albumId: number, mediaIds?: number[]) =>
    api.post<DownloadJob>(`/client/albums/${albumId}/download-jobs`, mediaIds ? { media_ids: mediaIds } : {}),

  getDownloadJobStatus: (jobId: number) => api.get<DownloadJob>(`/client/download-jobs/${jobId}`),

  cancelDownloadJob: (jobId: number) => api.post<DownloadJob>(`/client/download-jobs/${jobId}/cancel`),

  verifyDownloadPassword: (password: string) =>
    api.post<{ verified: boolean }>("/client/verify-download-password", { password }),

  downloadJobFileUrl: (jobId: number) => `${API_BASE_URL}/api/client/download-jobs/${jobId}/file`,
};
