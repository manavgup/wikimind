import type { ClipRecord, ExtensionSettings, IngestStatus } from "../types";

const DEFAULT_GATEWAY_URL = "http://localhost:7842";
const MAX_RECENT_CLIPS = 20;

export async function getSettings(): Promise<ExtensionSettings> {
  const { gatewayUrl } = await chrome.storage.local.get("gatewayUrl");
  return { gatewayUrl: (gatewayUrl as string) ?? DEFAULT_GATEWAY_URL };
}

export async function setGatewayUrl(url: string): Promise<void> {
  await chrome.storage.local.set({ gatewayUrl: url });
}

export async function getRecentClips(): Promise<ClipRecord[]> {
  const { recentClips } = await chrome.storage.local.get("recentClips");
  return (recentClips as ClipRecord[]) ?? [];
}

export async function addRecentClip(clip: ClipRecord): Promise<void> {
  const clips = await getRecentClips();
  clips.unshift(clip);
  await chrome.storage.local.set({
    recentClips: clips.slice(0, MAX_RECENT_CLIPS),
  });
}

export async function updateClipStatus(
  sourceId: string,
  status: IngestStatus
): Promise<void> {
  const clips = await getRecentClips();
  const idx = clips.findIndex((c) => c.sourceId === sourceId);
  if (idx !== -1) {
    clips[idx].status = status;
    await chrome.storage.local.set({ recentClips: clips });
  }
}
