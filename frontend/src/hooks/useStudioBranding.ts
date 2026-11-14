import { useEffect, useSyncExternalStore } from "react";
import { BrandingState, getBrandingState, refreshBranding, subscribeBranding } from "../services/studioBranding";

// Name and logo of the signed-in studio (studio admin UI only).
export function useStudioBranding(): BrandingState {
  const state = useSyncExternalStore(subscribeBranding, getBrandingState);
  useEffect(() => {
    refreshBranding();
  }, []);
  return state;
}
