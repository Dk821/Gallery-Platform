import { useEffect, useState } from "react";
import { galleryService } from "./gallery";

// The studio that shared a gallery link: its name, logo and contact details, shown to the CLIENT on the
// login page, the gallery header and the footer. It comes from the public gallery-access check
// (GET /api/client/gallery/access/{galleryId}), so it works before the client has signed in, and it is
// kept per gallery link so moving between the client's pages never re-fetches or flickers.

export interface ClientStudio {
  name: string;
  // The studio's name as used in gallery links (/<slug>/gallery/<id>); null for a studio without one.
  slug?: string | null;
  logo_url: string | null;
  brand_color: string | null;
  contact_email: string | null;
  contact_phone: string | null;
}

export type ClientBrandingState =
  | { status: "loading"; studio: null }
  | { status: "ready"; studio: ClientStudio | null } // null = not mapped to a studio -> the default look
  | { status: "failed"; studio: null };

const known = new Map<string, ClientStudio | null>();
const inflight = new Map<string, Promise<ClientStudio | null>>();

/** Lets a page that already made the access check hand over its answer instead of asking again. */
export function primeClientBranding(galleryId: string, studio: ClientStudio | null | undefined) {
  known.set(galleryId, studio ?? null);
}

function load(galleryId: string): Promise<ClientStudio | null> {
  let p = inflight.get(galleryId);
  if (!p) {
    p = galleryService
      .checkGalleryAccess(galleryId)
      .then((a) => {
        const studio = a.studio ?? null;
        known.set(galleryId, studio);
        return studio;
      })
      .finally(() => inflight.delete(galleryId));
    inflight.set(galleryId, p);
  }
  return p;
}

export function useClientBranding(galleryId: string): ClientBrandingState {
  const [state, setState] = useState<ClientBrandingState>(() =>
    known.has(galleryId) ? { status: "ready", studio: known.get(galleryId) ?? null } : { status: "loading", studio: null }
  );

  useEffect(() => {
    if (known.has(galleryId)) {
      setState({ status: "ready", studio: known.get(galleryId) ?? null });
      return;
    }
    let cancelled = false;
    setState({ status: "loading", studio: null });
    load(galleryId)
      .then((studio) => !cancelled && setState({ status: "ready", studio }))
      .catch(() => !cancelled && setState({ status: "failed", studio: null }));
    return () => {
      cancelled = true;
    };
  }, [galleryId]);

  return state;
}
