import { CSSProperties, FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

type FloatStyle = CSSProperties & Record<`--${string}`, string | number>;

// The same quiet gold bokeh the admin sign-in and the 404 page drift behind
// their cards, so the studio's own lens language carries over to the front
// door instead of inventing a third decoration.
const BOKEH: { left: string; top: string; size: number; duration: number; delay: number; opacity: number; drift: number; rotate: number }[] = [
  { left: "6%", top: "72%", size: 90, duration: 17, delay: -2, opacity: 0.7, drift: 24, rotate: 15 },
  { left: "14%", top: "14%", size: 46, duration: 13, delay: -8, opacity: 0.55, drift: -18, rotate: -20 },
  { left: "88%", top: "66%", size: 64, duration: 19, delay: -5, opacity: 0.6, drift: -26, rotate: 25 },
  { left: "82%", top: "10%", size: 40, duration: 14, delay: -11, opacity: 0.5, drift: 20, rotate: -15 },
  { left: "46%", top: "88%", size: 54, duration: 21, delay: -3, opacity: 0.5, drift: 14, rotate: 10 },
  { left: "93%", top: "86%", size: 34, duration: 16, delay: -6, opacity: 0.45, drift: -12, rotate: 20 },
];

// A gallery id is a UUID (or a demo word), never a dotted hostname, so this
// charset is what tells a pasted id apart from a pasted bare URL.
const GALLERY_ID_RE = /^[A-Za-z0-9_-]+$/;

// Clients arrive with the full link their photographer sent, not a bare id,
// so look for the "/gallery/<id>" segment first (any trailing /view, /wishlist
// or query string still resolves to the same gallery) and only then treat the
// whole input as an id. Anything else returns null so the field can say so
// rather than navigating somewhere meaningless.
function extractGalleryId(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const fromLink = trimmed.match(/\/gallery\/([^/?#]+)/i);
  const candidate = fromLink ? fromLink[1] : trimmed;
  return GALLERY_ID_RE.test(candidate) ? candidate : null;
}

export default function Home() {
  const navigate = useNavigate();
  const [galleryLink, setGalleryLink] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  function handleOpenGallery(e: FormEvent) {
    e.preventDefault();
    const galleryId = extractGalleryId(galleryLink);
    if (!galleryId) {
      setLinkError("Paste the gallery link from your photographer's email or text.");
      return;
    }
    navigate(`/gallery/${galleryId}`);
  }

  return (
    <div className="home-page">
      <div className="login-float-layer" aria-hidden="true">
        {BOKEH.map((b, i) => (
          <span
            key={i}
            className="login-float login-float--bokeh"
            style={
              {
                left: b.left,
                top: b.top,
                width: b.size,
                height: b.size,
                animationDuration: `${b.duration}s`,
                animationDelay: `${b.delay}s`,
                "--float-opacity": b.opacity,
                "--float-drift": `${b.drift}px`,
                "--float-rotate": `${b.rotate}deg`,
              } as FloatStyle
            }
          />
        ))}
      </div>

      <main className="home-shell">
        {/* Hero — the logo is the only thing that needs to be said first. */}
        <section className="home-hero">
          <img className="home-mark" src="/ls-logo.png" alt="Love Story Photography logo" width={72} height={72} />
          <div className="login-brand home-brand">
            <span className="login-brand__script">Love Story</span>
            <span className="login-brand__sub">Photography</span>
          </div>

          <p className="home-kicker">Wedding &amp; Portrait Photography</p>
          <h1 className="home-title">Every frame of your story, kept private.</h1>
          <div className="home-rule" aria-hidden="true" />
          <p className="home-subtitle">
            A password-protected home for your photographs and films — delivered by the studio,
            curated by you.
          </p>

          {/* <div className="home-cta">
            <button
              type="button"
              className="home-btn home-btn--primary"
              onClick={() => galleryInputRef.current?.focus()}
            >
              Open your gallery
            </button>
            <button
              type="button"
              className="home-btn home-btn--ghost"
              onClick={() => navigate("/admin/login")}
            >
              Studio admin
            </button>
          </div> */}
        </section>

        {/* Portals — the two ways into the app, and the only two. */}
        <section className="home-portals" aria-label="Ways in">
          <article className="home-portal">
            <span className="home-portal__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path
                  d="M12 20.3C8.6 17.4 4 13.6 4 9.9 4 7.5 5.9 5.7 8.2 5.7c1.3 0 2.6.7 3.8 2 1.2-1.3 2.5-2 3.8-2 2.3 0 4.2 1.8 4.2 4.2 0 3.7-4.6 7.5-8 10.4Z"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <h2 className="home-portal__title">Your gallery</h2>
            <p className="home-portal__text">
              Paste the private link from your photographer and your photographs, films and
              favourites are waiting.
            </p>

            <form className="home-portal__form" onSubmit={handleOpenGallery} aria-label="Open a client gallery">
              {linkError && (
                <p className="home-error" role="alert">
                  {linkError}
                </p>
              )}
              <label className="home-portal__label" htmlFor="gallery-link">
                Gallery link
              </label>
              <input
                id="gallery-link"
                className="home-portal__input"
                type="text"
                value={galleryLink}
                onChange={(e) => {
                  setGalleryLink(e.target.value);
                  if (linkError) setLinkError(null);
                }}
                placeholder="https://…/gallery/your-link"
                autoComplete="off"
                spellCheck={false}
                ref={galleryInputRef}
              />
              <button type="submit" className="home-btn home-btn--primary home-portal__submit">
                Open my gallery
              </button>
            </form>
          </article>

        </section>

        <footer className="home-footer">
          <span>Love Story Photography</span>
          <span className="home-footer__dot" aria-hidden="true" />
          <span>Private galleries, delivered with care</span>
        </footer>
      </main>
    </div>
  );
}
