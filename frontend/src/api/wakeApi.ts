// Waking the API before the visitor needs it.
//
// Render's free tier suspends the API after ~15 minutes idle, the same as the
// AI service. The login page is static and draws at once, so a visitor would
// type their details, press a button, and only then start a ~25-second boot
// with nothing on screen to explain it. Knocking as soon as the page appears
// spends that boot on the time they are reading and typing instead.
//
// Like the AI service, a suspended API holds a browser's connection open
// until it has booted, so a plain request to /health is the whole wake-up.

import { API_BASE_URL } from "./client";

// /health lives beside /api, not under it.
const API_ORIGIN = API_BASE_URL.replace(/\/api\/?$/, "");

// Cold boots have been measured around 25s. The ceiling is for one going
// badly, not for the normal case.
const WAKE_TIMEOUT_MS = 90_000;

let inFlight: Promise<boolean> | null = null;

/** Resolves true once the API answers. Well under a second when it is up. */
export function wakeApi(): Promise<boolean> {
  inFlight ??= fetch(`${API_ORIGIN}/health`, { signal: AbortSignal.timeout(WAKE_TIMEOUT_MS) })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}
