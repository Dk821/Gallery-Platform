import { AlbumComment, api, API_BASE_URL, DownloadJob, MediaItem, Page } from "./api";

export interface GalleryInfo {
  client_name: string;
  client_uuid: string;
  has_download_password: boolean;
  // Whole-gallery totals, aggregated in SQL by the backend
  // (media_service.get_client_media_totals) rather than counted from the
  // album pages the landing page happened to load - a page of rows would
  // undercount any album bigger than that page.
  total_files: number;
  total_photos: number;
  total_videos: number;
  total_bytes: number;
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
  // Aggregated server-side alongside media_count (see album_service
  // .list_albums_for_client) - the album page renders these instead of
  // counting the media rows it happened to load, which undercounts any
  // album bigger than one page.
  photo_count: number;
  video_count: number;
  total_bytes: number;
  // Whether the admin has switched on the page-turning Book View for this
  // album. Purely a presentation flag - the client's access to the
  // album's media is governed entirely by the normal auth/expiry checks,
  // same as every other client-facing field here.
  book_view_enabled: boolean;
  book_layout?: 'square' | 'portrait' | 'landscape';
  // How many page notes this client has written on this album. Counted in
  // the database (one grouped query for the whole page of albums), so the
  // UI never has to count the notes it happened to load.
  comment_count?: number;
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

  // --- Book View page notes ---
  // The signed-in client's own notes for the pages of one album, in book
  // order. There is at most ONE note per page, so saving a page again edits
  // the existing note instead of stacking duplicates - which is what makes
  // the Book View's "type, submit, turn the page" flow safe to retry.
  listAlbumComments: (albumId: number) => api.get<AlbumComment[]>(`/client/albums/${albumId}/comments`),

  // mediaId is the item on that page, pageNumber is its 1-based page number.
  // The server verifies the media belongs to this client's album and stores
  // the note against the client resolved from the session cookie.
  saveAlbumComment: (albumId: number, payload: { media_id: number; page_number: number; comment: string }) =>
    api.post<AlbumComment & { created: boolean }>(`/client/albums/${albumId}/comments`, payload),

  updateAlbumComment: (commentId: number, comment: string) =>
    api.put<AlbumComment>(`/client/comments/${commentId}`, { comment }),

  deleteAlbumComment: (commentId: number) => api.delete<null>(`/client/comments/${commentId}`),

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