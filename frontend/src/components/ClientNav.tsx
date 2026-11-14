import { useLocation, useNavigate } from "react-router-dom";
import { useGalleryBase } from "../hooks/useGalleryBase";
import { authService } from "../services/auth";
import { useClientBranding } from "../services/clientBranding";
import ClientBrandMark from "./ClientBrandMark";

interface ClientNavProps {
  galleryId: string;
}

export default function ClientNav({ galleryId }: ClientNavProps) {
  const navigate = useNavigate();
  const galleryBase = useGalleryBase();
  const branding = useClientBranding(galleryId);
  const onWishlistPage = useLocation().pathname === `${galleryBase}/wishlist`;

  async function handleLogout() {
    try {
      await authService.logout();
    } catch {
      // Ignore network / session errors on logout
    }
    navigate(`${galleryBase}`, { replace: true });
  }

  return (
    <header className="sam-nav">
      <button
        type="button"
        className="sam-nav__brand"
        onClick={() => navigate(`${galleryBase}/view`)}
        aria-label={`${branding.studio?.name ?? "Love Story Photography"} Home`}
      >
        <ClientBrandMark studio={branding.studio} variant="nav" pending={branding.status === "loading"} />
      </button>

      <div className="sam-nav__right">
        <span className="sam-nav__tagline">
          <span className="sam-nav__heart-icon" aria-hidden="true">
            ♡
          </span>
          <span>A story to remember</span>
        </span>

        <span className="sam-nav__divider" aria-hidden="true" />

        <button
          type="button"
          className={`sam-nav__wishlist-btn${onWishlistPage ? " is-current" : ""}`}
          onClick={() => navigate(`${galleryBase}/wishlist`)}
          aria-label="My wishlist"
          aria-current={onWishlistPage ? "page" : undefined}
        >
          <svg viewBox="0 0 24 24" fill={onWishlistPage ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
          </svg>
          <span>Wishlist</span>
        </button>

        <button
          type="button"
          className="sam-nav__logout-btn"
          onClick={handleLogout}
          aria-label="Logout from gallery"
        >
          <svg
            className="sam-nav__logout-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l3 3m0 0l-3 3m3-3H3"
            />
          </svg>
          <span>Logout</span>
        </button>
      </div>
    </header>
  );
}
