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
                <div className="flex items-center gap-1.5 truncate">
                  {c.parent_conversation_id && (
                    <svg
                      className="h-3 w-3 flex-shrink-0 text-purple-500"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      aria-label="Branch"
                    >
                      <path d="M5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM5 12.75a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM4.25 4.5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5a.75.75 0 0 1 .75-.75ZM11 4.5a.75.75 0 0 1 .75.75v1a2.25 2.25 0 0 1-2.25 2.25H6.56l1.22-1.22a.75.75 0 0 0-1.06-1.06l-2.5 2.5a.75.75 0 0 0 0 1.06l2.5 2.5a.75.75 0 1 0 1.06-1.06L6.56 10h2.94A3.75 3.75 0 0 0 13.25 6.25v-1A.75.75 0 0 0 12.5 4.5Z"/>
                    </svg>
                  )}
                  <span className="truncate">{c.title}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                  <span>{relativeTime(c.updated_at)}</span>
                  <span>•</span>
                  <span>{c.turn_count} turn{c.turn_count === 1 ? "" : "s"}</span>
                  {c.fork_count > 0 && (
                    <>
                      <span>•</span>
                      <span>{c.fork_count} fork{c.fork_count === 1 ? "" : "s"}</span>
                    </>
                  )}
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
