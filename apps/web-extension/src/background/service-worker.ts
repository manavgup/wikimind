import { getSource } from "../lib/api";
import { getRecentClips, updateClipStatus } from "../lib/storage";
import type { IngestStatus } from "../types";

const TERMINAL_STATUSES: IngestStatus[] = ["compiled", "failed"];
const POLL_INTERVAL_MS = 5000;
const MAX_POLL_ATTEMPTS = 60; // 5 minutes max

/** Poll a single source until it reaches a terminal status. */
async function pollSource(sourceId: string, attempt = 0): Promise<void> {
  if (attempt >= MAX_POLL_ATTEMPTS) return;

  try {
    const source = await getSource(sourceId);
    if (TERMINAL_STATUSES.includes(source.status)) {
      await updateClipStatus(sourceId, source.status);
      return;
    }
  } catch {
    // Server unreachable or source deleted — stop polling.
    return;
  }

  setTimeout(() => pollSource(sourceId, attempt + 1), POLL_INTERVAL_MS);
}

/** Check all recent clips for non-terminal statuses and start polling. */
async function pollPendingClips(): Promise<void> {
  const clips = await getRecentClips();
  for (const clip of clips) {
    if (!TERMINAL_STATUSES.includes(clip.status)) {
      void pollSource(clip.sourceId);
    }
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "clip:success") {
    chrome.action.setBadgeText({ text: "\u2713" });
    chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);

    // Start polling the newly clipped source.
    if (msg.sourceId) {
      void pollSource(msg.sourceId);
    }
  }

  if (msg.type === "clip:error") {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 5000);
  }

  sendResponse({ ok: true });
  return false;
});

// On service worker startup, poll any clips still in progress.
void pollPendingClips();
