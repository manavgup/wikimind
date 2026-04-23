import { useState, useEffect } from "preact/hooks";
import type { Source, ClipRecord } from "../../types";
import { clipUrl } from "../../lib/api";
import { addRecentClip, getRecentClips } from "../../lib/storage";
import { ClipButton } from "./ClipButton";
import { StatusBadge } from "./StatusBadge";
import { RecentClips } from "./RecentClips";

export type ClipState = "idle" | "clipping" | "success" | "error";

const UNCLIPPABLE_PREFIXES = ["chrome://", "edge://", "about:", "chrome-extension://"];

function isClippableUrl(url: string): boolean {
  return !UNCLIPPABLE_PREFIXES.some((prefix) => url.startsWith(prefix));
}

export function ClipTab() {
  const [clipState, setClipState] = useState<ClipState>("idle");
  const [currentSource, setCurrentSource] = useState<Source | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [currentUrl, setCurrentUrl] = useState("");
  const [recentClips, setRecentClips] = useState<ClipRecord[]>([]);

  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.url) setCurrentUrl(tabs[0].url);
    });
    getRecentClips().then((clips) => setRecentClips(clips.slice(0, 5)));
  }, []);

  async function handleClip() {
    if (!currentUrl || clipState === "clipping") return;

    setClipState("clipping");
    setErrorMsg(null);

    try {
      const source = await clipUrl(currentUrl);
      setCurrentSource(source);
      setClipState("success");

      const clip: ClipRecord = {
        sourceId: source.id,
        url: currentUrl,
        title: source.title,
        status: source.status,
        clippedAt: new Date().toISOString(),
      };
      await addRecentClip(clip);
      setRecentClips((await getRecentClips()).slice(0, 5));

      chrome.runtime.sendMessage({ type: "clip:success" });
    } catch (err) {
      setClipState("error");
      const msg = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(msg);
      chrome.runtime.sendMessage({ type: "clip:error" });
    }
  }

  const canClip = currentUrl !== "" && isClippableUrl(currentUrl);

  return (
    <div>
      <div style={{ marginBottom: "12px" }}>
        {currentUrl && isClippableUrl(currentUrl) ? (
          <p
            style={{
              fontSize: "12px",
              color: "#64748b",
              margin: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {currentUrl}
          </p>
        ) : currentUrl ? (
          <p style={{ fontSize: "12px", color: "#94a3b8", margin: 0 }}>
            Cannot clip internal browser pages
          </p>
        ) : (
          <p style={{ fontSize: "12px", color: "#94a3b8", margin: 0 }}>
            No URL detected
          </p>
        )}
      </div>

      <ClipButton state={clipState} onClick={handleClip} disabled={!canClip} />

      {clipState === "success" && currentSource && (
        <div style={{ marginTop: "8px" }}>
          <StatusBadge status={currentSource.status} />
        </div>
      )}
      {clipState === "error" && errorMsg && (
        <p style={{ marginTop: "8px", fontSize: "12px", color: "#ef4444" }}>
          {errorMsg}
        </p>
      )}

      {recentClips.length > 0 && (
        <div style={{ marginTop: "16px" }}>
          <RecentClips clips={recentClips} />
        </div>
      )}
    </div>
  );
}
