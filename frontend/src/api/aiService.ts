// Waking the AI service, from the one place a wake-up call actually works.
//
// Render's free tier suspends a service after ~15 minutes of no traffic, and
// how that sleep behaves depends on who knocks. A browser hitting a suspended
// service has its connection held until the boot finishes - measured at 41.4s,
// then a 200. The API calling the AI service next door is refused outright, in
// about 1.5s. So the same sleep is patience in one place and an error in the
// other, and the first segmentation after an idle spell came back as a failure
// within seconds.
//
// Two attempts to absorb that inside the API client were reverted: waiting only
// helps if something is holding the connection open, and internally nothing is.
// The knock has to come from the browser, which is what this does.

const AI_SERVICE_URL = import.meta.env.VITE_AI_SERVICE_URL;

// A cold boot was measured at 41.4s. The ceiling is for a boot going worse
// than that, not for the normal case.
const WAKE_TIMEOUT_MS = 90_000;

export type WakeResult = "awake" | "unreachable" | "not-configured";

let inFlight: Promise<WakeResult> | null = null;

async function knock(): Promise<WakeResult> {
  try {
    const response = await fetch(`${AI_SERVICE_URL}/health`, {
      signal: AbortSignal.timeout(WAKE_TIMEOUT_MS),
    });
    return response.ok ? "awake" : "unreachable";
  } catch {
    // A timeout, a refused connection, a DNS failure: from here they are the
    // same answer - there is nothing to segment with yet.
    return "unreachable";
  }
}

/** Wait for the AI service to be answering, waking it if it is suspended.
    Resolves in well under a second when it is already up. */
export function wakeAiService(): Promise<WakeResult> {
  // Only the deployed frontend sets this. Under compose and in local dev the
  // AI service does not sleep, so there is nothing to wake and no reason to
  // make the page wait on a request to a service it never talks to directly.
  if (!AI_SERVICE_URL) return Promise.resolve("not-configured");

  // One knock at a time, shared by every caller: a remount, or a second page
  // asking, should wait on the boot already in progress rather than start its
  // own 40-second wait. Cleared when it settles, since the service will sleep
  // again after the next idle spell.
  inFlight ??= knock().finally(() => {
    inFlight = null;
  });
  return inFlight;
}
