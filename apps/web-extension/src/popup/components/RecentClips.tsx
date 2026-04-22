import type { ClipRecord } from "../../types";
import { StatusBadge } from "./StatusBadge";

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function truncateUrl(url: string, maxLen = 40): string {
  try {
    const parsed = new URL(url);
    const display = parsed.hostname + parsed.pathname;
    return display.length > maxLen
      ? display.slice(0, maxLen - 1) + "\u2026"
      : display;
  } catch {
    return url.length > maxLen ? url.slice(0, maxLen - 1) + "\u2026" : url;
  }
}

interface Props {
  clips: ClipRecord[];
}

export function RecentClips({ clips }: Props) {
  return (
    <div>
      <h2
        style={{
          fontSize: "12px",
          fontWeight: 600,
          color: "#64748b",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          margin: "0 0 8px 0",
        }}
      >
        Recent
      </h2>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {clips.map((clip) => (
          <li
            key={clip.sourceId}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "6px 0",
              borderBottom: "1px solid #e2e8f0",
              gap: "8px",
            }}
          >
            <span
              style={{
                fontSize: "12px",
                color: "#334155",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
              }}
              title={clip.url}
            >
              {clip.title ?? truncateUrl(clip.url)}
            </span>
            <StatusBadge status={clip.status} />
            <span
              style={{
                fontSize: "11px",
                color: "#94a3b8",
                whiteSpace: "nowrap",
              }}
            >
              {timeAgo(clip.clippedAt)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
