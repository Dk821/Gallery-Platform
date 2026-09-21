import { useCallback, useRef, useState } from "react";
import { ApiRequestError } from "../services/api";
import { galleryService } from "../services/gallery";

interface UseWishlistOptions {
  // Demo galleries (test-uuid / preview / demo) have no backend rows, so a
  // toggle there stays local instead of calling an API that would just fail.
  demo?: boolean;
  // Called with a human-readable message when a toggle could not be saved and
  // has been rolled back. The page decides how to show it (its own toast).
  onError?: (message: string) => void;
}

interface HasWishlistFlag {
  id: number;
  is_wishlisted: boolean;
}

// The client's wishlist state for whatever media is currently on screen.
//
// - No request per photo: every media list/detail response already carries
//   `is_wishlisted`, and seed() just copies those flags in as pages arrive.
// - Optimistic: toggle() flips the heart immediately, then calls
//   POST/DELETE /client/wishlist/{id}, and rolls back (with onError) if the
//   server refuses. Nothing is reloaded.
// - One in-flight request per photo: a second click on the same photo while
//   its request is still running is ignored, so responses can never land out
//   of order and leave the heart disagreeing with the server.
export function useWishlist({ demo = false, onError }: UseWishlistOptions = {}) {
  const [ids, setIds] = useState<Set<number>>(() => new Set());
  // A ref mirrors the state so toggle() always reads the latest value
  // synchronously, never a stale render's closure.
  const idsRef = useRef(ids);
  const pendingRef = useRef<Set<number>>(new Set());
  const demoRef = useRef(demo);
  const onErrorRef = useRef(onError);
  demoRef.current = demo;
  onErrorRef.current = onError;

  const apply = useCallback((update: (prev: Set<number>) => Set<number>) => {
    const next = update(idsRef.current);
    idsRef.current = next;
    setIds(next);
  }, []);

  // Merge the server's flags for FRESHLY LOADED items (a page 1 load, or a
  // "load more" page). Call it with just the new items - re-seeding an older
  // page would overwrite a heart the user has since toggled. A photo whose
  // toggle is in flight keeps its optimistic value.
  const seed = useCallback(
    (items: HasWishlistFlag[]) => {
      apply((prev) => {
        const next = new Set(prev);
        for (const item of items) {
          if (pendingRef.current.has(item.id)) continue;
          if (item.is_wishlisted) next.add(item.id);
          else next.delete(item.id);
        }
        return next;
      });
    },
    [apply]
  );

  const isWishlisted = useCallback((id: number) => ids.has(id), [ids]);

  const toggle = useCallback(
    async (id: number): Promise<void> => {
      if (pendingRef.current.has(id)) return;
      const wasWishlisted = idsRef.current.has(id);
      pendingRef.current.add(id);

      // Optimistic update.
      apply((prev) => {
        const next = new Set(prev);
        if (wasWishlisted) next.delete(id);
        else next.add(id);
        return next;
      });

      if (demoRef.current) {
        pendingRef.current.delete(id);
        return;
      }

      try {
        if (wasWishlisted) await galleryService.removeFromWishlist(id);
        else await galleryService.addToWishlist(id);
      } catch (err) {
        // Roll back to what the server still has.
        apply((prev) => {
          const next = new Set(prev);
          if (wasWishlisted) next.add(id);
          else next.delete(id);
          return next;
        });
        const expired = err instanceof ApiRequestError && err.code === "ALBUM_EXPIRED";
        onErrorRef.current?.(
          expired ? "This album is no longer available." : "Couldn't update your wishlist. Please try again."
        );
      } finally {
        pendingRef.current.delete(id);
      }
    },
    [apply]
  );

  return { isWishlisted, toggle, seed, count: ids.size };
}
