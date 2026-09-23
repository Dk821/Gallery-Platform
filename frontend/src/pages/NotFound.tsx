import { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";

type FloatStyle = CSSProperties & Record<`--${string}`, string | number>;

// Quiet, fixed set of "bokeh" circles - the same photographers' lens
// language used on the sign-in pages - drifting slowly behind the 404
// card so an unknown route still feels like part of the studio.
const BOKEH: { left: string; top: string; size: number; duration: number; delay: number; opacity: number; drift: number; rotate: number }[] = [
  { left: "6%", top: "68%", size: 90, duration: 17, delay: -2, opacity: 0.7, drift: 24, rotate: 15 },
  { left: "16%", top: "16%", size: 46, duration: 13, delay: -8, opacity: 0.55, drift: -18, rotate: -20 },
  { left: "87%", top: "62%", size: 64, duration: 19, delay: -5, opacity: 0.6, drift: -26, rotate: 25 },
  { left: "80%", top: "12%", size: 40, duration: 14, delay: -11, opacity: 0.5, drift: 20, rotate: -15 },
  { left: "48%", top: "86%", size: 54, duration: 21, delay: -3, opacity: 0.5, drift: 14, rotate: 10 },
  { left: "92%", top: "88%", size: 34, duration: 16, delay: -6, opacity: 0.45, drift: -12, rotate: 20 },
];

export default function NotFound() {
  const navigate = useNavigate();

  return (
    <div className="notfound-page">
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

      <div className="notfound-card">
        <div className="login-brand">
          <span className="login-brand__script">Love Story</span>
          <span className="login-brand__sub">Photography</span>
        </div>

        <p className="notfound-code">404</p>
        <h1>This moment never got captured.</h1>
        <p className="notfound-message">
          The page you're looking for has drifted out of frame — it may have moved, or it never
          existed in the first place.
        </p>

        <div className="notfound-actions">
          <button type="button" className="notfound-btn notfound-btn--primary" onClick={() => navigate("/admin/dashboard")}>
            Back to dashboard
          </button>
          <button type="button" className="notfound-btn notfound-btn--ghost" onClick={() => navigate(-1)}>
            Go back
          </button>
        </div>
      </div>
    </div>
  );
}