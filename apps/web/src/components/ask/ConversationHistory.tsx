import { Link } from "react-router-dom";
import type { ConversationSummary } from "../../api/query";

interface Props {
  conversations: ConversationSummary[];
  activeId?: string;
}

export function ConversationHistory({ conversations, activeId }: Props) {
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Conversations
        </h2>
        <Link
          to="/ask"
          className="text-xs font-medium text-blue-600 hover:underline"
        >
          + New
        </Link>
      </div>
      {conversations.length === 0 ? (
        <p className="text-xs text-slate-400">No conversations yet.</p>
      ) : (
        <ul className="space-y-1">
          {conversations.map((c) => (
            <li key={c.id}>
              <Link
                to={`/ask/${c.id}`}
                className={`block rounded px-2 py-2 text-sm hover:bg-slate-100 ${
                  c.id === activeId ? "bg-slate-100 font-medium" : ""
                }`}
              >
                <div className="truncate">{c.title}</div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                  <span>{relativeTime(c.updated_at)}</span>
                  <span>•</span>
                  <span>{c.turn_count} turn{c.turn_count === 1 ? "" : "s"}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
