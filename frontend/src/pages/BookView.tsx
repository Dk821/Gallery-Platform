import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties, MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import BookCommentPanel from "../components/BookCommentPanel";
import { AlbumComment, ApiRequestError } from "../services/api";
import { GalleryAlbum, GalleryMedia, galleryService } from "../services/gallery";

// How long the closed cover is shown before it opens by itself (autoplay on).
const COVER_HOLD_MS = 2200;
// The book never opens until the first spread has loaded (otherwise the pages
// swing open onto black). If it is very slow, open anyway after this long.
const COVER_READY_TIMEOUT_MS = 10000;
// How long the front cover takes to swing open. A hard cover is slower and
// stiffer than a paper page.
const COVER_OPEN_MS = 2900;
// How much of the normal page curl the stiff cover gets (0 = rigid board).
const COVER_BEND_SCALE = 0.3;

// How long an auto-played page stays up before turning to the next one.
const AUTOPLAY_INTERVAL_MS = 5000;
// How many items ahead/behind of the current page get their full-size
// image warmed in the browser cache, so the next couple of turns never
// wait on a network round trip.
const PRELOAD_AHEAD = 3;
const PRELOAD_BEHIND = 2;
// Minimum horizontal drag, in px, that counts as a swipe rather than a tap.
const SWIPE_THRESHOLD_PX = 40;

// ---- Phone view ------------------------------------------------------------
// On a phone held upright the book is replaced by a "rotate your device"
// screen; held sideways it gets the cinematic layout. The tool bar (zoom,
// reset, play, fullscreen, share) shows on every screen. The two media
// queries live in book-view.css - this one must stay identical to the
// portrait one there.
const PHONE_PORTRAIT_QUERY = "(orientation: portrait) and (pointer: coarse) and (max-width: 600px)";
// Zoom is a multiplier (1 = 100%) applied to the whole book.
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEP = 0.25;
// How far past the zoomed book's edge a drag may pull it, in px.
const PAN_OVERSHOOT_PX = 48;
// Studio WhatsApp number for the green chat button, digits only with country
// code (e.g. "919876543210"). Leave empty to hide the button.
const BOOK_WHATSAPP_NUMBER = "";
const BOOK_WHATSAPP_TEXT = "Hello! I am viewing my wedding album and would like to talk.";
// How long the small "Link copied" message stays up.
const TOAST_MS = 2200;

// ---- Page-turn model ------------------------------------------------------
// The turning page is not one rigid slab but a chain of narrow strips, each
// hinged to the previous one. Every strip curls back from its parent while the
// page is in motion, so the free edge trails the spine side and the paper arcs
// like a real page. More strips = a smoother arc. The total curl lives in CSS:
// --book-curl-total (it is split evenly across the hinges).
const LEAF_SEGMENTS = 12;
const FLIP_DURATION_MS = 2600;

// Smooth sine ease-in-out: starts and ends very gently, hangs in the middle.
const easeInOutSine = (t: number) => -(Math.cos(Math.PI * t) - 1) / 2;

// How much the paper is curled at turn progress p (0..1). Squared sine: it is
// 0 at both ends, 1 half-way through, and rises SLOWER than the turn itself
// near the ends. That last part matters - the page's outer edge must always
// stay above the page underneath, and a plain sine would let a strong curl push
// it through the surface right at the start / end of the turn.
const bendAt = (p: number) => Math.pow(Math.sin(Math.PI * p), 2);

/**
 * Drives one turn: a requestAnimationFrame loop writes --p (0 -> 1, eased turn
 * progress) and --bend (0 -> 1 -> 0, how far the paper is curled) on the book
 * element; CSS turns those into transforms. Completion never depends on a
 * browser event firing, so a hidden tab can't leave the book stuck mid-turn.
 * Returns a cancel function.
 */
function animateTurn(book: HTMLElement, durationMs: number, bendScale: number, onDone: () => void) {
  const setPose = (p: number) => {
    book.style.setProperty("--p", p.toFixed(4));
    book.style.setProperty("--bend", (bendAt(p) * bendScale).toFixed(4));
  };

  // Runs before the browser paints, so the first frame is always the resting
  // pose, never a stale end pose from the previous turn.
  setPose(0);

  let raf = 0;
  let startTime: number | null = null;
  const tick = (now: number) => {
    // Timed from the first painted frame so the opening of the turn is
    // never skipped by the work of mounting the leaf.
    if (startTime === null) startTime = now;
    const t = Math.min((now - startTime) / durationMs, 1);
    setPose(easeInOutSine(t));
    if (t < 1) raf = requestAnimationFrame(tick);
    else onDone();
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

const prefersReducedMotion = () => !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

// Keeps a zoomed book from being dragged completely out of view. At 100% or
// less there is nothing to pan, so the offset is always zero.
function limitPan(book: HTMLElement | null, pan: { x: number; y: number }, zoom: number) {
  if (!book || zoom <= 1) return { x: 0, y: 0 };
  const maxX = (book.offsetWidth * (zoom - 1)) / 2 + PAN_OVERSHOOT_PX;
  const maxY = (book.offsetHeight * (zoom - 1)) / 2 + PAN_OVERSHOOT_PX;
  return { x: clamp(pan.x, -maxX, maxX), y: clamp(pan.y, -maxY, maxY) };
}

function touchDistance(e: ReactTouchEvent) {
  const a = e.touches[0];
  const b = e.touches[1];
  if (!a || !b) return 0;
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

// Vendor-prefixed fullscreen / orientation-lock bits the DOM typings omit.
type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitFullscreenEnabled?: boolean;
  webkitExitFullscreen?: () => Promise<void> | void;
};
type FullscreenElement = HTMLElement & { webkitRequestFullscreen?: () => Promise<void> | void };
type LockableOrientation = ScreenOrientation & { lock?: (orientation: string) => Promise<void> };

type FlipDirection = "next" | "prev";
interface Flip {
  direction: FlipDirection;
  to: number;
}

// closed  = front cover only, centred
// opening = the cover is swinging open
// open    = a normal open book
type BookPhase = "closed" | "opening" | "open";

interface CoverInfo {
  title: string;
}

/**
 * One half of a spread. A photo is laid across BOTH pages: the left page shows
 * its left half, the right page its right half. Each page renders the whole
 * photo at twice its own width and lets `overflow: hidden` on the page crop
 * away the other half.
 * Videos can't be split, so their poster stands in here; the playable video
 * is a separate overlay (see .book-video).
 */
function SpreadHalf({ item, half, describe = false }: { item: GalleryMedia; half: 0 | 1; describe?: boolean }) {
  const isVideo = item.file_type === "video";
  const src = isVideo ? galleryService.thumbnailUrl(item.id) : galleryService.viewUrl(item.id);
  return (
    <div className={`book-spread book-spread--${half === 0 ? "left" : "right"}`}>
      <img
        className={`book-spread-img${isVideo ? " is-video" : ""}`}
        src={src}
        alt={describe ? item.title || item.file_name : ""}
        draggable={false}
        decoding="sync"
      />
    </div>
  );
}

/**
 * One vertical slice of a turning-page face. `half` says which half of the
 * spread photo this face shows; `slice` picks the strip-wide window of that
 * half. The photo is drawn at full spread size and shifted so only that
 * window shows through the strip.
 */
function LeafSlice({ item, half, slice }: { item: GalleryMedia; half: 0 | 1; slice: number }) {
  const isVideo = item.file_type === "video";
  const src = isVideo ? galleryService.thumbnailUrl(item.id) : galleryService.viewUrl(item.id);
  return (
    <div className="book-seg__slice" style={{ "--k": slice, "--half": half } as CSSProperties}>
      <img className={`book-spread-img${isVideo ? " is-video" : ""}`} src={src} alt="" draggable={false} decoding="sync" />
    </div>
  );
}

/**
 * The same idea for the front cover: the leather cover art is drawn at full
 * page size and shifted so only this strip's window of it shows through.
 */
function CoverSlice({ cover, slice }: { cover: CoverInfo; slice: number }) {
  return (
    <div className="book-seg__slice book-seg__slice--cover" style={{ "--k": slice } as CSSProperties}>
      <div className="book-cover-art">
        <span className="book-cover-art__title">{cover.title}</span>
        <span className="book-cover-art__ornament">
          <i />
        </span>
      </div>
    </div>
  );
}

/**
 * One hinged strip of the turning page. Strips nest: each child sits at the far
 * edge of its parent, so rotating a parent carries every strip after it.
 *
 * A real leaf has two sides, and here they are two different spreads:
 *   Next  (leaf starts on the RIGHT, mirror = false):
 *     front = RIGHT half of the current photo,  back = LEFT half of the next photo
 *   Prev  (leaf starts on the LEFT,  mirror = true):
 *     front = LEFT half of the current photo,   back = RIGHT half of the previous photo
 *   Cover (leaf starts on the RIGHT, `cover` given):
 *     front = the leather front cover,          back = LEFT half of the first photo
 * When the leaf lands, its back face is exactly what the page it landed on
 * shows next, so the hand-over to the static pages is invisible.
 */
function LeafSegment({
  index,
  frontItem,
  backItem,
  mirror,
  cover,
}: {
  index: number;
  frontItem?: GalleryMedia | null;
  backItem: GalleryMedia;
  mirror: boolean;
  cover?: CoverInfo;
}) {
  const isTail = index === LEAF_SEGMENTS - 1;
  // Strips are counted out from the spine. The spine is the LEFT edge of a
  // right-hand page and the RIGHT edge of a left-hand page, and the back face
  // is mirrored, hence the flipped slice order.
  const frontSlice = mirror ? LEAF_SEGMENTS - 1 - index : index;
  const backSlice = mirror ? index : LEAF_SEGMENTS - 1 - index;
  const frontHalf = mirror ? 0 : 1;
  const backHalf = mirror ? 1 : 0;
  return (
    <div className={`book-seg${isTail ? " book-seg--tail" : ""}`} style={{ "--i": index } as CSSProperties}>
      <div className="book-seg__face book-seg__face--front">
        {cover ? (
          <CoverSlice cover={cover} slice={frontSlice} />
        ) : (
          frontItem && <LeafSlice item={frontItem} half={frontHalf} slice={frontSlice} />
        )}
      </div>
      <div className="book-seg__face book-seg__face--back">
        <LeafSlice item={backItem} half={backHalf} slice={backSlice} />
      </div>
      {!isTail && (
        <LeafSegment index={index + 1} frontItem={frontItem} backItem={backItem} mirror={mirror} cover={cover} />
      )}
    </div>
  );
}

export default function BookView() {
  const { galleryId = "", albumId = "" } = useParams();
  const navigate = useNavigate();
  const albumIdNum = Number(albumId);

  const [album, setAlbum] = useState<GalleryAlbum | null>(null);
  const [items, setItems] = useState<GalleryMedia[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Page notes, keyed by the 1-based page (spread) number they belong to.
  // A page holds at most one note per client, so a map is the natural shape.
  const [comments, setComments] = useState<Record<number, AlbumComment>>({});
  const [commentOpen, setCommentOpen] = useState(false);
  const [commentSaving, setCommentSaving] = useState(false);
  const [commentError, setCommentError] = useState<string | null>(null);

  const [currentIndex, setCurrentIndex] = useState(0);
  const [flip, setFlip] = useState<Flip | null>(null);
  const [autoplay, setAutoplay] = useState(true);
  // The book starts CLOSED and opens by itself (unless the visitor prefers
  // reduced motion, then it just starts open).
  const [phase, setPhase] = useState<BookPhase>(() => (prefersReducedMotion() ? "open" : "closed"));
  // True once the first spread's picture is downloaded and decoded.
  const [coverReady, setCoverReady] = useState(false);

  // The ref sits on .book-cover (not .flipbook) so --p / --bend reach the
  // floor shadow and the paper-finish light as well as the turning leaf.
  const bookRef = useRef<HTMLDivElement>(null);
  const flipLock = useRef(false);
  const touchStartX = useRef<number | null>(null);
  // Keep the actual load/decode promise, so a turn can wait for the exact
  // target image instead of merely assuming that a preload has finished.
  const imageReady = useRef<Map<number, Promise<void>>>(new Map());

  // ---- Phone view state ---------------------------------------------------
  const shellRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // True while a phone is held upright (the rotate prompt is on screen).
  const [phonePortrait, setPhonePortrait] = useState(() => !!window.matchMedia?.(PHONE_PORTRAIT_QUERY)?.matches);
  const touchStartY = useRef<number | null>(null);
  const panOrigin = useRef({ x: 0, y: 0 });
  const pinchStart = useRef<{ dist: number; zoom: number } | null>(null);
  // Mouse drag of a zoomed-in book (desktop). `suppressClick` stops the drag's
  // mouse-up from also turning a page.
  const mouseDrag = useRef<{ x: number; y: number; origin: { x: number; y: number }; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const toastTimer = useRef<number | undefined>(undefined);

  // Live orientation tracking: follows the same media query the stylesheet uses.
  useEffect(() => {
    const mq = window.matchMedia?.(PHONE_PORTRAIT_QUERY);
    if (!mq) return;
    const update = () => setPhonePortrait(mq.matches);
    update();
    if (mq.addEventListener) {
      mq.addEventListener("change", update);
      return () => mq.removeEventListener("change", update);
    }
    mq.addListener(update);
    return () => mq.removeListener(update);
  }, []);

  useEffect(() => {
    const doc = document as FullscreenDocument;
    const onChange = () => {
      const active = !!(doc.fullscreenElement || doc.webkitFullscreenElement);
      setIsFullscreen(active);
      if (!active) {
        try {
          screen.orientation?.unlock?.();
        } catch {
          /* orientation lock was never taken */
        }
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, []);

  useEffect(
    () => () => {
      window.clearTimeout(toastTimer.current);
    },
    []
  );

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const drag = mouseDrag.current;
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      setDragging(true);
      setPan(limitPan(bookRef.current, { x: drag.origin.x + dx, y: drag.origin.y + dy }, zoom));
    };
    const onUp = () => {
      const drag = mouseDrag.current;
      if (!drag) return;
      mouseDrag.current = null;
      setDragging(false);
      if (drag.moved) {
        suppressClick.current = true;
        window.setTimeout(() => {
          suppressClick.current = false;
        }, 0);
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [zoom]);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), TOAST_MS);
  }, []);

  const changeZoom = useCallback((next: number) => {
    const z = Math.round(clamp(next, ZOOM_MIN, ZOOM_MAX) * 100) / 100;
    setZoom(z);
    setPan((p) => limitPan(bookRef.current, p, z));
  }, []);

  // ---- Load the album + every media item in it -------------------------
  //
  // Reuses the exact same client-facing endpoints the normal grid uses
  // (getAlbum / listMedia) - no new backend route for Book View itself.
  // getAlbum already enforces "this client owns this album" and "this
  // album hasn't expired" (get_album_for_client_or_403 /
  // check_album_not_expired on the backend), so Book View inherits the
  // same access control as every other client-facing page for free.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const albumData = await galleryService.getAlbum(albumIdNum);
        if (cancelled) return;

        if (!albumData.book_view_enabled) {
          navigate(`/gallery/${galleryId}/view/${albumId}`, { replace: true });
          return;
        }
        setAlbum(albumData);

        const collected: GalleryMedia[] = [];
        let page = 1;
        // Matches the album/media size this platform is built around
        // (Upload-Pipeline.md); a safety ceiling, not an expected album size.
        const HARD_CAP = 2000;
        for (;;) {
          const res = await galleryService.listMedia(albumIdNum, page, 200);
          collected.push(...res.items);
          if (!res.has_more || collected.length >= HARD_CAP) break;
          page += 1;
        }
        if (cancelled) return;

        // The studio's saved book order is the reading order. id only breaks
        // ties left by two uploads that raced for the same sort_order.
        collected.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
        setItems(collected);
        setCurrentIndex(0);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiRequestError && (err.code === "ALBUM_EXPIRED" || err.code === "ALBUM_FORBIDDEN")) {
          navigate(`/gallery/${galleryId}`, { replace: true });
        } else {
          setError(err instanceof Error ? err.message : "Could not load this album.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [albumIdNum]);

  // ---- Load the client's page notes --------------------------------------
  //
  // Deliberately separate from the album load: notes are a bonus, so the book
  // must never wait on them, and a failure here leaves the album readable.
  useEffect(() => {
    let cancelled = false;

    async function loadNotes() {
      try {
        const loaded = await galleryService.listAlbumComments(albumIdNum);
        if (cancelled) return;
        const byPage: Record<number, AlbumComment> = {};
        for (const note of loaded) byPage[note.page_number] = note;
        setComments(byPage);
      } catch {
        /* notes are non-essential to viewing the album */
      }
    }

    setComments({});
    loadNotes();
    return () => {
      cancelled = true;
    };
  }, [albumIdNum]);

  // ---- Preload nearby pages ---------------------------------------------
  useEffect(() => {
    if (items.length === 0) return;
    const wanted: number[] = [];
    for (let d = 1; d <= PRELOAD_AHEAD; d++) wanted.push(currentIndex + d);
    for (let d = 1; d <= PRELOAD_BEHIND; d++) wanted.push(currentIndex - d);

    wanted
      .filter((i) => i >= 0 && i < items.length)
      .forEach((i) => {
        const item = items[i];
        if (!item || imageReady.current.has(item.id)) return;
        const img = new Image();
        // Videos turn as their poster, so that is what needs to be warm.
        img.src = item.file_type === "photo" ? galleryService.viewUrl(item.id) : galleryService.thumbnailUrl(item.id);
        const ready = typeof img.decode === "function"
          ? img.decode().then(() => undefined, () => undefined)
          : new Promise<void>((resolve) => {
              img.onload = () => resolve();
              img.onerror = () => resolve();
            });
        imageReady.current.set(item.id, ready);
      });
  }, [currentIndex, items]);

  // ---- Derived book faces ------------------------------------------------
  //
  // Every photo is a SPREAD: it fills the whole open book, its left half on
  // the left page and its right half on the right page. currentIndex is the
  // spread on show. Which spread each surface shows during a turn is what
  // keeps the animation free of pops:
  //
  //  Next (c -> c+1): the leaf starts on the right showing the right half of
  //    spread c, and lands on the left showing the left half of spread c+1.
  //    The right page is pre-advanced to c+1 so it is already there as the
  //    leaf lifts away; the left page stays at c until the leaf covers it.
  //
  //  Prev (c -> c-1): the leaf starts on the left showing the left half of
  //    spread c, and lands on the right showing the right half of spread c-1.
  //    The left page is pre-rewound to c-1 so it is revealed as the leaf
  //    lifts away; the right page stays at c until the leaf covers it.
  //
  //  Opening: while the book is closed or opening, the right page already
  //    shows the right half of the FIRST spread (hidden under the cover), and
  //    the cover leaf's back face is the left half of that same spread.
  const currentItem = items[currentIndex] ?? null;
  const targetItem = flip ? items[flip.to] ?? null : null;
  // The page number the client sees (1-based), and their note for it if any.
  const currentPageNumber = currentIndex + 1;
  const currentComment = comments[currentPageNumber] ?? null;

  const turningNext = flip?.direction === "next";
  const turningPrev = flip?.direction === "prev";

  const leftItem = turningPrev ? targetItem : currentItem;
  const rightItem = turningNext ? targetItem : currentItem;

  // The page a turning leaf lands on keeps showing the OLD spread until the
  // leaf covers it. If the NEW spread is only mounted when the turn ends, the
  // browser has to load/decode/paint a huge photo right as the leaf is removed,
  // and the page shows a blank paper-white gap for a couple of seconds. So for
  // the length of the turn the incoming spread is already mounted underneath
  // (first in the list = lower in the stack), fully decoded and painted. Keyed
  // by item id so that same <img> simply becomes the page when the turn ends.
  const leftItems: GalleryMedia[] =
    turningNext && currentItem && targetItem ? [targetItem, currentItem] : leftItem ? [leftItem] : [];
  const rightItems: GalleryMedia[] =
    turningPrev && currentItem && targetItem ? [targetItem, currentItem] : rightItem ? [rightItem] : [];

  const isOpen = phase === "open";
  const coverInfo: CoverInfo = { title: album?.album_name ?? "" };

  // A video can't be split across two pages, so while one is on show it sits in
  // a single overlay across the whole spread. It is removed the moment a turn
  // starts (the poster halves underneath take over) and comes back after.
  const showVideo = isOpen && !flip && currentItem?.file_type === "video";

  // ---- Get the first spread ready before the cover opens -----------------
  useEffect(() => {
    const first = items[0];
    if (!first) return;
    let cancelled = false;
    const finish = () => {
      if (!cancelled) setCoverReady(true);
    };
    const img = new Image();
    img.src = first.file_type === "photo" ? galleryService.viewUrl(first.id) : galleryService.thumbnailUrl(first.id);
    if (typeof img.decode === "function") {
      img.decode().then(finish, finish);
    } else {
      img.onload = finish;
      img.onerror = finish;
    }
    const timer = setTimeout(finish, COVER_READY_TIMEOUT_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [items]);

  // ---- Opening the book --------------------------------------------------
  const openBook = useCallback(() => {
    if (flipLock.current || phase !== "closed" || !coverReady) return;
    flipLock.current = true;
    // The left page is hidden under the cover until the book is open, so its
    // photo has never been decoded. Decode it BEFORE the cover starts to swing,
    // otherwise the page goes blank the moment the cover lands.
    const pageImages = Array.from(bookRef.current?.querySelectorAll<HTMLImageElement>(".book-page img") ?? []);
    Promise.all(
      pageImages.map((img) => (typeof img.decode === "function" ? img.decode().catch(() => undefined) : undefined))
    ).then(() => setPhase("opening"));
  }, [phase, coverReady]);

  // Hold on the closed cover for a moment, then open it (autoplay only: pause
  // to linger on the cover and tap it when ready).
  useEffect(() => {
    if (phase !== "closed" || loading || items.length === 0 || !autoplay || !coverReady || phonePortrait) return;
    const id = setTimeout(openBook, COVER_HOLD_MS);
    return () => clearTimeout(id);
  }, [phase, loading, items.length, autoplay, coverReady, phonePortrait, openBook]);

  useLayoutEffect(() => {
    if (phase !== "opening") return;
    const book = bookRef.current;
    const done = () => {
      flipLock.current = false;
      setPhase("open");
    };
    if (!book || prefersReducedMotion()) {
      done();
      return;
    }
    return animateTurn(book, COVER_OPEN_MS, COVER_BEND_SCALE, done);
  }, [phase]);

  // ---- Flip mechanics ----------------------------------------------------
  const startFlip = useCallback(async (direction: FlipDirection, to: number) => {
    if (flipLock.current) return;
    flipLock.current = true;
    const item = items[to];
    if (item) {
      let ready = imageReady.current.get(item.id);
      if (!ready) {
        const img = new Image();
        img.src = item.file_type === "photo" ? galleryService.viewUrl(item.id) : galleryService.thumbnailUrl(item.id);
        ready = typeof img.decode === "function"
          ? img.decode().then(() => undefined, () => undefined)
          : new Promise<void>((resolve) => {
              img.onload = () => resolve();
              img.onerror = () => resolve();
            });
        imageReady.current.set(item.id, ready);
      }
      await ready;
    }
    setFlip({ direction, to });
  }, [items]);

  const goNext = useCallback(() => {
    if (phase === "closed") {
      openBook();
      return;
    }
    if (phase !== "open") return;
    if (currentIndex < items.length - 1) startFlip("next", currentIndex + 1);
  }, [phase, openBook, currentIndex, items.length, startFlip]);

  const goPrev = useCallback(() => {
    if (phase !== "open") return;
    if (currentIndex > 0) startFlip("prev", currentIndex - 1);
  }, [phase, currentIndex, startFlip]);

  // Instant, unanimated page change - used for autoplay looping from the last
  // page back to the first, and for the scrubber. Jumping while the book is
  // still closed just opens it at that page.
  const jumpTo = useCallback(
    (targetIndex: number) => {
      if (flipLock.current || targetIndex < 0 || targetIndex >= items.length) return;
      if (phase === "closed") setPhase("open");
      if (targetIndex !== currentIndex) setCurrentIndex(targetIndex);
    },
    [phase, currentIndex, items.length]
  );

  useLayoutEffect(() => {
    if (!flip) return;
    const book = bookRef.current;
    let cancelled = false;
    let paintFrame = 0;
    let cancelTurn: (() => void) | undefined;
    const commit = () => {
      flipLock.current = false;
      setCurrentIndex(flip.to);
      setFlip(null);
    };
    if (!book || prefersReducedMotion()) {
      commit();
      return;
    }
    const beginWhenPainted = async () => {
      // The detached preload warms the network/cache, but the actual images
      // mounted on the turning leaf also need to decode before it moves - and
      // so do the ones on the resting pages, including the incoming spread
      // waiting under the page the leaf will land on. Decoding them now, not
      // when the leaf is removed, is what keeps the landing page from going blank.
      const leafImages = Array.from(book.querySelectorAll<HTMLImageElement>(".book-leaf img, .book-page img"));
      try {
        await Promise.all(leafImages.map((img) => {
          if (typeof img.decode === "function") return img.decode();
          if (img.complete && img.naturalWidth > 0) return Promise.resolve();
          return new Promise<void>((resolve, reject) => {
            img.onload = () => resolve();
            img.onerror = () => reject(new Error("Page image failed to load"));
          });
        }));
      } catch {
        if (cancelled) return;
        flipLock.current = false;
        setFlip(null);
        showToast("This page could not be loaded. Please try again.");
        return;
      }
      if (cancelled) return;
      // Let the decoded leaf paint once in its resting pose before animating.
      await new Promise<void>((resolve) => {
        paintFrame = requestAnimationFrame(() => resolve());
      });
      if (!cancelled) cancelTurn = animateTurn(book, FLIP_DURATION_MS, 1, commit);
    };
    void beginWhenPainted();
    return () => {
      cancelled = true;
      if (paintFrame) cancelAnimationFrame(paintFrame);
      cancelTurn?.();
    };
  }, [flip, showToast]);

  // ---- Page notes --------------------------------------------------------
  //
  // The sheet belongs to the page currently on show. Saving closes it and
  // turns to the next page (the natural reading rhythm); the backend upserts
  // on client + album + page, so re-saving edits the same note.
  const openCommentSheet = useCallback(() => {
    if (phase !== "open" || flip || !currentItem) return;
    setCommentError(null);
    setCommentOpen(true);
  }, [phase, flip, currentItem]);

  const closeCommentSheet = useCallback(() => {
    if (commentSaving) return;
    setCommentOpen(false);
    setCommentError(null);
  }, [commentSaving]);

  const submitComment = useCallback(
    async (text: string) => {
      if (!currentItem || commentSaving) return;
      const pageNumber = currentIndex + 1;
      const existing = comments[pageNumber];
      // Nothing changed: don't write again. A pointless write would reopen a
      // note the studio had already resolved.
      if (existing && existing.comment.trim() === text) {
        setCommentOpen(false);
        goNext();
        return;
      }
      setCommentSaving(true);
      setCommentError(null);
      try {
        const saved = await galleryService.saveAlbumComment(albumIdNum, {
          media_id: currentItem.id,
          page_number: pageNumber,
          comment: text,
        });
        setComments((prev) => ({ ...prev, [saved.page_number]: saved }));
        setCommentOpen(false);
        if (currentIndex >= items.length - 1) showToast("Note saved");
        else goNext();
      } catch (err) {
        setCommentError(err instanceof Error ? err.message : "Could not save your note.");
      } finally {
        setCommentSaving(false);
      }
    },
    [albumIdNum, commentSaving, comments, currentIndex, currentItem, goNext, items.length, showToast]
  );

  const deleteComment = useCallback(async () => {
    const pageNumber = currentIndex + 1;
    const existing = comments[pageNumber];
    if (!existing || commentSaving) return;
    setCommentSaving(true);
    setCommentError(null);
    try {
      await galleryService.deleteAlbumComment(existing.id);
      setComments((prev) => {
        const next = { ...prev };
        delete next[pageNumber];
        return next;
      });
      setCommentOpen(false);
      showToast("Note removed");
    } catch (err) {
      setCommentError(err instanceof Error ? err.message : "Could not remove your note.");
    } finally {
      setCommentSaving(false);
    }
  }, [commentSaving, comments, currentIndex, showToast]);

  // ---- Keyboard, swipe, tap zones ----------------------------------------
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // The note sheet owns the keyboard while it is up (Escape closes it).
      if (commentOpen) return;
      if (e.key === "ArrowRight") goNext();
      else if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "Escape") navigate(`/gallery/${galleryId}/view/${albumId}`);
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [commentOpen, goNext, goPrev, navigate, galleryId, albumId]);

  // One finger swipes the page; when the book is zoomed in, one finger drags
  // it around instead; two fingers pinch-zoom.
  function handleTouchStart(e: ReactTouchEvent) {
    if (e.touches.length === 2) {
      pinchStart.current = { dist: touchDistance(e), zoom };
      touchStartX.current = null;
      return;
    }
    touchStartX.current = e.touches[0]?.clientX ?? null;
    touchStartY.current = e.touches[0]?.clientY ?? null;
    panOrigin.current = pan;
  }

  function handleTouchMove(e: ReactTouchEvent) {
    if (pinchStart.current && e.touches.length === 2) {
      const start = pinchStart.current;
      if (start.dist > 0) changeZoom(start.zoom * (touchDistance(e) / start.dist));
      return;
    }
    const touch = e.touches[0];
    if (zoom <= 1 || !touch || touchStartX.current === null || touchStartY.current === null) return;
    setDragging(true);
    setPan(
      limitPan(
        bookRef.current,
        {
          x: panOrigin.current.x + touch.clientX - touchStartX.current,
          y: panOrigin.current.y + touch.clientY - touchStartY.current,
        },
        zoom
      )
    );
  }

  function handleMouseDown(e: ReactMouseEvent) {
    if (zoom <= 1 || e.button !== 0) return;
    if ((e.target as HTMLElement).closest("video")) return;
    mouseDrag.current = { x: e.clientX, y: e.clientY, origin: pan, moved: false };
  }

  function handleStageClickCapture(e: ReactMouseEvent) {
    if (!suppressClick.current) return;
    e.stopPropagation();
    e.preventDefault();
  }

  function handleTouchCancel() {
    pinchStart.current = null;
    touchStartX.current = null;
    touchStartY.current = null;
    setDragging(false);
  }

  function handleTouchEnd(e: ReactTouchEvent) {
    if (pinchStart.current) {
      if (e.touches.length === 0) pinchStart.current = null;
      touchStartX.current = null;
      return;
    }
    setDragging(false);
    if (touchStartX.current === null) return;
    const endX = e.changedTouches[0]?.clientX ?? touchStartX.current;
    const delta = endX - touchStartX.current;
    touchStartX.current = null;
    touchStartY.current = null;
    // Zoomed in, a drag moves the book rather than turning the page.
    if (zoom > 1) return;
    if (Math.abs(delta) < SWIPE_THRESHOLD_PX) return;
    if (delta < 0) goNext();
    else goPrev();
  }

  async function toggleFullscreen() {
    const doc = document as FullscreenDocument;
    const shell = shellRef.current as FullscreenElement | null;
    try {
      if (doc.fullscreenElement || doc.webkitFullscreenElement) {
        if (doc.exitFullscreen) await doc.exitFullscreen();
        else await doc.webkitExitFullscreen?.();
      } else if (shell) {
        if (shell.requestFullscreen) await shell.requestFullscreen();
        else await shell.webkitRequestFullscreen?.();
        // Keep the phone sideways while fullscreen (not every browser allows it).
        try {
          await (screen.orientation as LockableOrientation | undefined)?.lock?.("landscape");
        } catch {
          /* orientation lock not available */
        }
      }
    } catch {
      /* the browser refused fullscreen */
    }
  }

  async function handleShare() {
    const url = window.location.href;
    const title = album?.album_name || "Album";
    try {
      if (navigator.share) {
        await navigator.share({ title, url });
        return;
      }
    } catch (err) {
      // The visitor closed the share sheet: nothing to do.
      if (err instanceof DOMException && err.name === "AbortError") return;
    }
    try {
      await navigator.clipboard.writeText(url);
      showToast("Link copied");
    } catch {
      showToast("Could not share this link");
    }
  }

  function handleScrub(e: ChangeEvent<HTMLInputElement>) {
    jumpTo(Number(e.target.value) - 1);
  }

  // ---- Autoplay ----------------------------------------------------------
  useEffect(() => {
    if (!autoplay || phase !== "open" || commentOpen || items.length < 2 || loading || flip || phonePortrait) return;
    // Don't turn the page away from a video someone may be watching.
    if (items[currentIndex]?.file_type === "video") return;
    const id = setTimeout(() => {
      if (currentIndex >= items.length - 1) jumpTo(0);
      else goNext();
    }, AUTOPLAY_INTERVAL_MS);
    return () => clearTimeout(id);
  }, [autoplay, phase, commentOpen, currentIndex, flip, items, loading, phonePortrait, goNext, jumpTo]);

  if (loading) {
    return (
      <div className="book-shell">
        <div className="book-loading">
          <div className="book-loading__spinner" aria-hidden="true" />
          <p>Opening the book…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="book-shell">
        <div className="book-error">
          <p>{error}</p>
          <button className="btn-secondary" onClick={() => navigate(`/gallery/${galleryId}/view/${albumId}`)}>
            Back to album
          </button>
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="book-shell">
        <div className="book-error">
          <p>This album has no pages yet.</p>
          <button className="btn-secondary" onClick={() => navigate(`/gallery/${galleryId}/view/${albumId}`)}>
            Back to album
          </button>
        </div>
      </div>
    );
  }

  // Where the gold part of the scrubber ends (matches the thumb position).
  const fillPct = items.length > 1 ? (currentIndex / (items.length - 1)) * 100 : 100;
  // "Next" is always available while the book is closed (it opens it).
  const nextDisabled = isOpen && currentIndex === items.length - 1;
  const prevDisabled = !isOpen || currentIndex === 0;
  // Phone view: the zoom wrapper only gets a transform once the book is moved,
  // so at 100% the book is laid out exactly as it always was.
  const zoomed = zoom !== 1 || pan.x !== 0 || pan.y !== 0;
  const fullscreenDoc = document as FullscreenDocument;
  const fullscreenSupported = !!(fullscreenDoc.fullscreenEnabled || fullscreenDoc.webkitFullscreenEnabled);

  return (
    <div className="book-shell" ref={shellRef}>
      <button
        type="button"
        className="book-close-btn"
        onClick={() => navigate(`/gallery/${galleryId}/view/${albumId}`)}
        aria-label="Close Book View"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>

      {/* Phone landscape only (hidden by CSS elsewhere): studio pill, top left,
          and the optional WhatsApp button next to the close button. */}
      <div className="book-brand">
        <img src="/light-ls-logo.png" alt="Studio logo" draggable={false} />
      </div>

      {BOOK_WHATSAPP_NUMBER && (
        <a
          className="book-chat-btn"
          href={`https://wa.me/${BOOK_WHATSAPP_NUMBER}?text=${encodeURIComponent(BOOK_WHATSAPP_TEXT)}`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Chat with the studio on WhatsApp"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        </a>
      )}

      <div className={`book-title-row${phase === "closed" ? " is-hidden" : ""}`}>
        <h1 className="book-title-row__name">{album?.album_name}</h1>
        <span className="book-title-row__ornament" aria-hidden="true">
          <i />
        </span>
      </div>

      <div
        className={`book-stage${zoom > 1 ? " is-zoomed" : ""}`}
        onMouseDown={handleMouseDown}
        onClickCapture={handleStageClickCapture}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchCancel}
      >
        <button
          type="button"
          className="book-nav-zone book-nav-zone--prev"
          onClick={goPrev}
          disabled={prevDisabled}
          aria-label="Previous page"
        />
        <button
          type="button"
          className="book-nav-zone book-nav-zone--next"
          onClick={goNext}
          disabled={nextDisabled}
          aria-label="Next page"
        />

        <div
          className={`book-zoom${dragging ? " is-dragging" : ""}`}
          style={zoomed ? { transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` } : undefined}
        >
          <div
            className="book-cover"
            ref={bookRef}
            data-book-layout={album?.book_layout ?? "landscape"}
            data-phase={phase}
            data-turn={flip?.direction}
            style={{ "--seg-n": LEAF_SEGMENTS } as CSSProperties}
          >
            <div className="book-floor-shadow" aria-hidden="true" />

            <div className="flipbook">
              <div className="book-board" aria-hidden="true" />
              <div className="book-backdrop" aria-hidden="true" />

              <div className="book-page book-page--left">
                {leftItems.map((item) => (
                  <SpreadHalf key={item.id} item={item} half={0} describe />
                ))}
              </div>

              <div className="book-page book-page--right">
                {rightItems.map((item) => (
                  <SpreadHalf key={item.id} item={item} half={1} />
                ))}
              </div>

              <div className="book-gutter" aria-hidden="true">
                <span className="book-gutter__cap" />
              </div>

              {showVideo && currentItem && (
                <div className="book-video">
                  <video
                    className="book-page-media"
                    controls
                    playsInline
                    preload="none"
                    poster={galleryService.thumbnailUrl(currentItem.id)}
                    src={galleryService.viewUrl(currentItem.id)}
                  />
                </div>
              )}

              {/* The front cover: sits closed on the right half, then swings
                  open onto the left. The same element stays mounted from
                  "closed" through "opening", so nothing pops when it starts. */}
              {!isOpen && items[0] && (
                <div className="book-leaf book-leaf--right book-leaf--cover" aria-hidden="true">
                  <LeafSegment index={0} backItem={items[0]} mirror={false} cover={coverInfo} />
                </div>
              )}

              {/* A turning page only exists while a turn is running. */}
              {flip && currentItem && targetItem && (
                <div className={`book-leaf book-leaf--${flip.direction === "next" ? "right" : "left"}`} aria-hidden="true">
                  <LeafSegment index={0} frontItem={currentItem} backItem={targetItem} mirror={flip.direction === "prev"} />
                </div>
              )}

              {/* Paper finish: spine fold, gloss, grain and the moving light.
                  Must stay the LAST child so it sits above everything. */}
              <div className="book-finish" aria-hidden="true" />
            </div>
          </div>
        </div>

        {phase === "closed" && (
          <button type="button" className="book-open-zone" onClick={openBook} aria-label="Open the book">
            <span className={`book-open-hint${coverReady ? "" : " is-preparing"}`}>
              {coverReady ? "Tap to open" : "Preparing your album…"}
            </span>
          </button>
        )}
      </div>

      <div className="book-controls">
        <button
          type="button"
          className="book-control-btn"
          onClick={goPrev}
          disabled={prevDisabled}
          aria-label="Previous page"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>

        <div className="book-progress">
          <input
            type="range"
            className="book-progress__range"
            min={1}
            max={items.length}
            step={1}
            value={currentIndex + 1}
            onChange={handleScrub}
            disabled={items.length < 2}
            aria-label="Jump to page"
            style={{ "--fill": `${fillPct}%` } as CSSProperties}
          />
          <span className="book-progress__count">
            <b>{currentIndex + 1}</b> of {items.length}
          </span>
        </div>

        <button
          type="button"
          className="book-control-btn"
          onClick={() => setAutoplay((v) => !v)}
          aria-label={autoplay ? "Pause automatic page turning" : "Resume automatic page turning"}
          aria-pressed={autoplay}
        >
          {autoplay ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <rect x="6" y="5" width="4" height="14" />
              <rect x="14" y="5" width="4" height="14" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <polygon points="6 3 20 12 6 21 6 3" />
            </svg>
          )}
        </button>

        <button
          type="button"
          className="book-control-btn"
          onClick={goNext}
          disabled={nextDisabled}
          aria-label="Next page"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>

      {/* ---- Phone only (CSS shows these in landscape on a phone) ------------ */}
      <div className="book-mbar" role="toolbar" aria-label="Album controls">
        <button
          type="button"
          className="book-mbtn"
          onClick={() => changeZoom(zoom - ZOOM_STEP)}
          disabled={zoom <= ZOOM_MIN}
          aria-label="Zoom out"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
            <line x1="8" y1="11" x2="14" y2="11" />
          </svg>
        </button>
        <span className="book-mbar__zoom" aria-live="polite">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          className="book-mbtn"
          onClick={() => changeZoom(zoom + ZOOM_STEP)}
          disabled={zoom >= ZOOM_MAX}
          aria-label="Zoom in"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
            <line x1="8" y1="11" x2="14" y2="11" />
            <line x1="11" y1="8" x2="11" y2="14" />
          </svg>
        </button>

        <span className="book-mbar__sep" aria-hidden="true" />

        <button
          type="button"
          className="book-mbtn"
          onClick={() => changeZoom(1)}
          disabled={!zoomed}
          aria-label="Reset zoom"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <polyline points="3 3 3 8 8 8" />
          </svg>
        </button>

        <span className="book-mbar__sep" aria-hidden="true" />

        <button
          type="button"
          className="book-mbtn"
          onClick={() => setAutoplay((v) => !v)}
          aria-pressed={autoplay}
          aria-label={autoplay ? "Pause automatic page turning" : "Resume automatic page turning"}
        >
          {autoplay ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="6" y="5" width="4" height="14" />
              <rect x="14" y="5" width="4" height="14" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polygon points="6 3 20 12 6 21 6 3" />
            </svg>
          )}
        </button>

        <span className="book-mbar__sep" aria-hidden="true" />

        <button
          type="button"
          className={`book-mbtn${currentComment ? " book-mbtn--has-note" : ""}`}
          onClick={openCommentSheet}
          disabled={!isOpen || !currentItem}
          title="Leave a note about this page"
          aria-label={currentComment ? "Edit your note for this page" : "Add a note on this page"}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            <line x1="8" y1="10" x2="16" y2="10" />
            <line x1="8" y1="14" x2="13" y2="14" />
          </svg>
        </button>

        {fullscreenSupported && (
          <>
            <span className="book-mbar__sep" aria-hidden="true" />
            <button
              type="button"
              className="book-mbtn"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
            >
              {isFullscreen ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="4 14 10 14 10 20" />
                  <polyline points="20 10 14 10 14 4" />
                  <line x1="14" y1="10" x2="21" y2="3" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="15 3 21 3 21 9" />
                  <polyline points="9 21 3 21 3 15" />
                  <line x1="21" y1="3" x2="14" y2="10" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              )}
            </button>
          </>
        )}

        <span className="book-mbar__sep" aria-hidden="true" />

        <button type="button" className="book-mbtn" onClick={handleShare} aria-label="Share this album">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
        </button>

        <span className="book-mbar__sep" aria-hidden="true" />

        <span className="book-mbar__count" aria-label={`Page ${currentIndex + 1} of ${items.length}`}>
          <b>{currentIndex + 1}</b> / {items.length}
        </span>
      </div>

      {commentOpen && currentItem && (
        <BookCommentPanel
          pageNumber={currentPageNumber}
          totalPages={items.length}
          initialValue={currentComment?.comment ?? ""}
          hasExisting={!!currentComment}
          saving={commentSaving}
          error={commentError}
          onSubmit={submitComment}
          onDelete={deleteComment}
          onClose={closeCommentSheet}
        />
      )}

      {toast && (
        <div className="book-toast" role="status">
          {toast}
        </div>
      )}

      {/* Phone held upright: the book waits until the phone is turned sideways. */}
      <div className="book-rotate" aria-hidden={!phonePortrait}>
        <div className="book-rotate__tile">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="6.5" y="2.5" width="11" height="19" rx="2.5" />
            <circle cx="12" cy="17.5" r="0.7" fill="currentColor" />
          </svg>
        </div>
        <h2 className="book-rotate__title">Cinematic View Ready</h2>
        <p className="book-rotate__text">
          Please <b>rotate your device</b> to landscape for the full immersive 3D experience.
        </p>
        <span className="book-rotate__pill">
          <i aria-hidden="true" />
          Live orientation tracking
        </span>
      </div>
    </div>
  );
}
