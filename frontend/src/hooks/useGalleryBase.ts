import { useParams } from "react-router-dom";

/**
 * The address of the gallery being viewed, without a trailing page:
 *   /<studio-slug>/gallery/<galleryId>   (the link a studio shares)
 *   /gallery/<galleryId>                 (older links, and studios without a slug)
 * Pages build every link and redirect from this, so a client stays on the same form of URL while
 * moving between the gallery, an album, the book view and the wishlist.
 */
export function galleryBasePath(galleryId: string, studioSlug?: string | null): string {
  return studioSlug ? `/${studioSlug}/gallery/${galleryId}` : `/gallery/${galleryId}`;
}

export function useGalleryBase(): string {
  const { studioSlug, galleryId = "" } = useParams();
  return galleryBasePath(galleryId, studioSlug);
}
