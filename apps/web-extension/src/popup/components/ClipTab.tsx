import { useState, useEffect } from "preact/hooks";
import type { Source, ClipRecord } from "../../types";
import { clipUrl, checkConnection } from "../../lib/api";
import { ApiError } from "../../lib/retry";
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
  const [connected, setConnected] = useState<boolean | null>(null);
  const [connectionMsg, setConnectionMsg] = useState<string>("");

  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.url) setCurrentUrl(tabs[0].url);
    });
    getRecentClips().then((clips) => setRecentClips(clips.slice(0, 5)));
    checkConnection().then(({ ok, message }) => {
      setConnected(ok);
      setConnectionMsg(message);
    });
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
      let msg: string;
      if (err instanceof ApiError && err.status === 401) {
        msg = "Authentication failed. Add your API token in Settings.";
      } else if (err instanceof TypeError) {
        msg =
          "Could not reach the WikiMind server. Ensure your instance is running and the URL in Settings is correct.";
      } else {
        msg = err instanceof Error ? err.message : "Unknown error";
      }
      setErrorMsg(msg);
      chrome.runtime.sendMessage({ type: "clip:error" });
    }
  }

  const canClip = currentUrl !== "" && isClippableUrl(currentUrl) && connected === true;

  if (connected === false) {
    return (
      <div>
        <div
          style={{
            padding: "16px",
            borderRadius: "8px",
            backgroundColor: "#fef2f2",
            border: "1px solid #fecaca",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: "24px", marginBottom: "8px" }}>&#9888;</div>
          <p
            style={{
              fontSize: "13px",
              fontWeight: 600,
              color: "#dc2626",
              margin: "0 0 8px",
            }}
          >
            WikiMind server not reachable
          </p>
          <p style={{ fontSize: "12px", color: "#64748b", margin: 0 }}>
            {connectionMsg}
          </p>
        </div>
        <p
          style={{
            fontSize: "11px",
            color: "#94a3b8",
            marginTop: "12px",
            textAlign: "center",
          }}
        >
          Open Settings &#9881; to configure your server URL.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: "12px" }}>
        {connected === null && (
          <p style={{ fontSize: "12px", color: "#94a3b8", margin: "0 0 4px" }}>
            Checking connection...
          </p>
        )}
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
