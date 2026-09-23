import { api, API_BASE_URL, DownloadJob, MediaItem, Page } from "./api";

export interface GalleryInfo {
  client_name: string;
  client_uuid: string;
  has_download_password: boolean;
  // Whether this gallery has an automatic cover yet. False for galleries that
  // haven't had an eligible photo uploaded since covers existed - the landing
  // page then keeps its default hero instead of requesting an image that
  // would 404.
  has_cover: boolean;
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
  // Public pre-login check: does THIS gallery (link id) require a password?
  // Returns client_name too, so a passwordless gallery can go straight to
  // its entrance without keeping the caller waiting on extra round-trips.
  // 404 => unknown gallery link.
  checkGalleryAccess: (galleryId: string) =>
    api.get<{ requires_password: boolean; client_name: string }>(
      `/client/gallery/access/${galleryId}`
    ),

  getGallery: () => api.get<GalleryInfo>("/client/gallery"),

  // The automatic cover of the signed-in client's own gallery. No id in the
  // URL: the server resolves the client from the session cookie, so there is
  // nothing to tamper with. Read-only - covers have no manual management.
  coverUrl: () => `${API_BASE_URL}/api/client/gallery/cover`,

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

  // --- Wishlist (favourites) ---
  // The signed-in client's wishlisted media, newest first. Media in albums
  // that have expired is left out, same as every other client listing.
  listWishlist: (page = 1, limit = 60, albumId?: number) => {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    if (albumId !== undefined) params.set("album_id", String(albumId));
    return api.get<Page<GalleryMedia>>(`/client/wishlist?${params.toString()}`);
  },

  // Both are idempotent server-side (adding twice / removing twice is fine).
  addToWishlist: (mediaId: number) =>
    api.post<{ media_id: number; is_wishlisted: boolean }>(`/client/wishlist/${mediaId}`),

  removeFromWishlist: (mediaId: number) =>
    api.delete<{ media_id: number; is_wishlisted: boolean }>(`/client/wishlist/${mediaId}`),

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
