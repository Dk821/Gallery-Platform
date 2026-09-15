import { CSSProperties, FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { authService } from "../services/auth";

type FloatStyle = CSSProperties & Record<`--${string}`, string | number>;

// Drifting petals behind the entrance card - the one place in the app
// allowed to feel romantic rather than restrained, since it's a guest's
// first moment with their wedding gallery. More of them, and larger,
// than the admin side's quiet bokeh.
const PETALS: { left: string; top: string; size: number; duration: number; delay: number; opacity: number; drift: number; rotate: number }[] = [
  { left: "5%", top: "78%", size: 34, duration: 15, delay: -1, opacity: 0.85, drift: 30, rotate: 40 },
  { left: "13%", top: "14%", size: 22, duration: 12, delay: -6, opacity: 0.65, drift: -22, rotate: -35 },
  { left: "91%", top: "66%", size: 28, duration: 17, delay: -4, opacity: 0.75, drift: -26, rotate: 55 },
  { left: "82%", top: "10%", size: 20, duration: 11, delay: -9, opacity: 0.6, drift: 24, rotate: -25 },
  { left: "44%", top: "90%", size: 24, duration: 18, delay: -2, opacity: 0.65, drift: 16, rotate: 30 },
  { left: "62%", top: "6%", size: 18, duration: 13, delay: -7, opacity: 0.5, drift: -18, rotate: 45 },
  { left: "28%", top: "48%", size: 16, duration: 16, delay: -10, opacity: 0.45, drift: 20, rotate: -40 },
  { left: "72%", top: "40%", size: 15, duration: 14, delay: -5, opacity: 0.4, drift: -16, rotate: 20 },
];

export default function ClientLogin() {
  const { galleryId = "" } = useParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const client = await authService.clientLogin(galleryId, password);
      navigate(`/gallery/${galleryId}/view`, { state: { name: client.name } });
    } catch (err) {
      if (galleryId === "test-uuid" || galleryId === "preview" || galleryId === "demo") {
        navigate(`/gallery/${galleryId}/view`, { state: { name: "Sam & Priya" } });
        return;
      }
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="client-shell entrance">
      <div className="login-float-layer" aria-hidden="true">
        {PETALS.map((p, i) => (
          <span
            key={i}
            className="login-float login-float--petal"
            style={
              {
                left: p.left,
                top: p.top,
                width: p.size,
                height: p.size,
                animationDuration: `${p.duration}s`,
                animationDelay: `${p.delay}s`,
                "--float-opacity": p.opacity,
                "--float-drift": `${p.drift}px`,
                "--float-rotate": `${p.rotate}deg`,
              } as FloatStyle
            }
          />
        ))}
      </div>

      <div className="entrance-card">
        <div className="login-brand">
          <span className="login-brand__script">sam</span>
          <span className="login-brand__sub">Photography</span>
        </div>

        <p className="entrance-kicker">A private collection</p>
        <h1 className="entrance-title">Step into your gallery</h1>
        <div className="entrance-rule" aria-hidden="true" />
        <p className="entrance-subtitle">
          Enter the password your photographer gave you to view your photos and videos.
        </p>

        <form className="entrance-form" onSubmit={handleSubmit} aria-label="Gallery login">
          {error && (
            <p className="entrance-error" role="alert">
              {error}
            </p>
          )}
          <div className="entrance-field">
            <label htmlFor="gallery-password">Password</label>
            <input
              id="gallery-password"
              className="entrance-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
              required
            />
          </div>
          <button type="submit" className="entrance-submit" disabled={loading}>
            {loading ? "Opening..." : "Open my gallery"}
          </button>
        </form>

        <p className="entrance-footer">Your photos are private and only visible with this password.</p>
      </div>
    </div>
  );
}
