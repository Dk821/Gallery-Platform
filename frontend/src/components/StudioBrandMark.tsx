import { useState } from "react";
import { useStudioBranding } from "../hooks/useStudioBranding";
import { assetUrl } from "../services/api";

// The brand block at the top of the studio admin sidebar / mobile top bar:
// the studio's logo and name. While the studio is loading it keeps its space
// (so nothing jumps); if it can't be loaded it shows the original brand.
export default function StudioBrandMark({ variant }: { variant: "sidebar" | "topbar" }) {
  const { studio, status } = useStudioBranding();
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const p = variant === "sidebar" ? "admin-sidebar" : "admin-topbar";

  if (status === "ready" && studio) {
    const src = assetUrl(studio.logo_url);
    const showLogo = !!src && failedSrc !== src;
    return (
      <div className={`${p}__brand ${p}__brand--studio`}>
        {showLogo && <img className={`${p}__logo-img`} src={src!} alt="" onError={() => setFailedSrc(src)} />}
        <span className={showLogo ? `${p}__studio-name` : `${p}__logo-script ${p}__logo-script--name`}>{studio.name}</span>
      </div>
    );
  }

  return (
    <div className={`${p}__brand`} style={{ visibility: status === "failed" ? "visible" : "hidden" }}>
      <span className={`${p}__logo-script`}>Love Story</span>
      <span className={`${p}__logo-sub`}>PHOTOGRAPHY</span>
    </div>
  );
}
