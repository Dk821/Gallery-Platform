import { api } from "./api";

// The signed-in studio's name and logo, for the studio admin UI. Fetched from
// the backend (GET /api/studio/profile) once and shared by everything that
// shows it - the sidebar, the mobile top bar and the dashboard - so moving
// between pages shows it instantly instead of re-fetching and flickering.

export interface StudioBranding {
  id: number;
  name: string;
  logo_url: string | null;
  brand_color: string | null;
}

export interface BrandingState {
  studio: StudioBranding | null;
  status: "idle" | "loading" | "ready" | "failed";
}

const FRESH_MS = 30_000;

let state: BrandingState = { studio: null, status: "idle" };
let fetchedAt = 0;
let generation = 0; // bumped on sign-in/out so a late response for the previous user is dropped
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function set(next: BrandingState) {
  state = next;
  listeners.forEach((fn) => fn());
}

export function getBrandingState(): BrandingState {
  return state;
}

export function subscribeBranding(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Fetches the studio, keeping whatever is already shown until the answer
// arrives (so a refresh never blanks the brand).
export function refreshBranding(): Promise<void> {
  if (inflight) return inflight;
  if (state.status === "ready" && Date.now() - fetchedAt < FRESH_MS) return Promise.resolve();
  const gen = generation;
  if (state.status !== "ready") set({ studio: null, status: "loading" });
  inflight = api
    .get<StudioBranding>("/studio/profile")
    .then((d) => {
      if (gen !== generation) return;
      fetchedAt = Date.now();
      set({ studio: { id: d.id, name: d.name, logo_url: d.logo_url ?? null, brand_color: d.brand_color ?? null }, status: "ready" });
    })
    .catch(() => {
      if (gen !== generation) return;
      // Keep showing a previously loaded studio; otherwise fall back to the default brand.
      if (state.status !== "ready") set({ studio: null, status: "failed" });
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

// Forget the studio (called when an admin signs in or out).
export function clearBranding() {
  generation += 1;
  inflight = null;
  fetchedAt = 0;
  set({ studio: null, status: "idle" });
}
