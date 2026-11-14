import { useState } from "react";
import { assetUrl } from "../services/api";
import { ClientStudio } from "../services/clientBranding";

// The studio's mark for the client side: its uploaded logo and name. A gallery that belongs to no studio
// (or whose studio could not be loaded) keeps the original "Love Story" lockup.
export default function ClientBrandMark({
  studio,
  variant,
  pending = false,
}: {
  studio: ClientStudio | null;
  variant: "login" | "nav";
  /** Still loading: keep the space but show nothing, so the default brand never flashes first. */
  pending?: boolean;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const p = variant === "login" ? "login-brand" : "sam-nav";

  if (pending) {
    return (
      <span className={`${p}__studio`} style={{ visibility: "hidden" }} aria-hidden="true">
        <span className={`${p}__studio-name`}>&nbsp;</span>
      </span>
    );
  }

  if (!studio) {
    return (
      <>
        <span className={variant === "login" ? "login-brand__script" : "sam-nav__logo-script"}>Love Story</span>
        <span className={variant === "login" ? "login-brand__sub" : "sam-nav__logo-sub"}>
          {variant === "login" ? "Photography" : "PHOTOGRAPHY"}
        </span>
      </>
    );
  }

  const src = assetUrl(studio.logo_url);
  const showLogo = !!src && failedSrc !== src;
  return (
    <span className={`${p}__studio`}>
      {showLogo && <img className={`${p}__logo-img`} src={src!} alt="" onError={() => setFailedSrc(src)} />}
      <span className={showLogo ? `${p}__studio-name` : `${p}__studio-name ${p}__studio-name--script`}>{studio.name}</span>
    </span>
  );
}
