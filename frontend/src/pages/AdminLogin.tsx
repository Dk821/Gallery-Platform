import { CSSProperties, FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authService } from "../services/auth";

type FloatStyle = CSSProperties & Record<`--${string}`, string | number>;

// Quiet, fixed set of "bokeh" circles - a photographer's own lens
// language - drifting slowly behind the sign-in card. Deliberately fewer
// and smaller than the client entrance's petals below: restrained, not
// romantic, to match the admin side's "back office" tone.
const BOKEH: { left: string; top: string; size: number; duration: number; delay: number; opacity: number; drift: number; rotate: number }[] = [
  { left: "6%", top: "68%", size: 90, duration: 17, delay: -2, opacity: 0.7, drift: 24, rotate: 15 },
  { left: "16%", top: "16%", size: 46, duration: 13, delay: -8, opacity: 0.55, drift: -18, rotate: -20 },
  { left: "87%", top: "62%", size: 64, duration: 19, delay: -5, opacity: 0.6, drift: -26, rotate: 25 },
  { left: "80%", top: "12%", size: 40, duration: 14, delay: -11, opacity: 0.5, drift: 20, rotate: -15 },
  { left: "48%", top: "86%", size: 54, duration: 21, delay: -3, opacity: 0.5, drift: 14, rotate: 10 },
  { left: "92%", top: "88%", size: 34, duration: 16, delay: -6, opacity: 0.45, drift: -12, rotate: 20 },
];

export default function AdminLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await authService.adminLogin(email, password);
      navigate("/admin/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
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

      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <span className="login-brand__script">sam</span>
          <span className="login-brand__sub">Photography</span>
          <span className="login-brand__tag">Studio Admin</span>
        </div>

        <h1>Sign in to your studio</h1>
        <p className="auth-subtitle" style={{ textAlign: "center", margin: "0 0 0.5rem" }}>
          Manage client galleries, uploads, and downloads from one dashboard.
        </p>

        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}
        <label>
          Email Address
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            placeholder="admin@samphotography.com"
            autoFocus
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            placeholder="••••••••"
            required
          />
        </label>
        <button type="submit" className="auth-card__submit" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
