import { useNavigate } from "react-router-dom";
import { authService } from "../services/auth";

interface ClientNavProps {
  galleryId: string;
}

export default function ClientNav({ galleryId }: ClientNavProps) {
  const navigate = useNavigate();

  async function handleLogout() {
    try {
      await authService.logout();
    } catch {
      // Ignore network / session errors on logout
    }
    navigate(`/gallery/${galleryId}`, { replace: true });
  }

  return (
    <header className="sam-nav">
      <button
        type="button"
        className="sam-nav__brand"
        onClick={() => navigate(`/gallery/${galleryId}/view`)}
        aria-label="Sam Photography Home"
      >
        <span className="sam-nav__logo-script">sam</span>
        <span className="sam-nav__logo-sub">PHOTOGRAPHY</span>
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
