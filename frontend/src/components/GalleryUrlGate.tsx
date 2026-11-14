import type { ReactNode } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { galleryBasePath } from "../hooks/useGalleryBase";
import { useClientBranding } from "../services/clientBranding";

/**
 * Keeps every client gallery page on its one canonical address, /<studio-slug>/gallery/<id>/...
 *
 *  - an older link (/gallery/<id>/...) is redirected to the studio's address;
 *  - a link with the wrong studio name in it is corrected to the real one;
 *  - a gallery whose studio has no slug stays on /gallery/<id>/....
 *
 * It asks the same public access check the pages already use (answered once per gallery and kept), and
 * shows the page as soon as that answer is in. If the check fails (unknown link, offline) the page is
 * shown anyway so it can report the problem itself.
 */
export default function GalleryUrlGate({ children }: { children: ReactNode }) {
  const { studioSlug, galleryId = "" } = useParams();
  const location = useLocation();
  const branding = useClientBranding(galleryId);

  if (branding.status === "loading") return null;

  if (branding.status === "ready") {
    const wanted = branding.studio?.slug || undefined;
    if (wanted !== studioSlug) {
      const current = galleryBasePath(galleryId, studioSlug);
      const rest = location.pathname.startsWith(current) ? location.pathname.slice(current.length) : "";
      return <Navigate to={`${galleryBasePath(galleryId, wanted)}${rest}${location.search}${location.hash}`} replace state={location.state} />;
    }
  }
  return <>{children}</>;
}
