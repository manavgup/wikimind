import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../../store/auth";
import { useWebSocketStore } from "../../store/websocket";
import { Badge } from "./Badge";

interface LayoutProps {
  children: ReactNode;
}

const NAV_ITEMS = [
  { to: "/inbox", label: "Inbox", icon: "📥" },
  { to: "/ask", label: "Ask", icon: "💬" },
  { to: "/wiki", label: "Wiki", icon: "📚" },
  { to: "/graph", label: "Graph", icon: "🕸️" },
  { to: "/health", label: "Health", icon: "🩺" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

export function Layout({ children }: LayoutProps) {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const wsState = useWebSocketStore((s) => s.state);
  const toasts = useWebSocketStore((s) => s.toasts);
  const dismissToast = useWebSocketStore((s) => s.dismissToast);

  return (
    <div className="flex h-screen w-screen bg-slate-50">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <Link to="/" className="flex items-center gap-2 px-5 py-5 border-b border-slate-200 cursor-pointer no-underline">
          <span className="text-xl">🧠</span>
          <span className="text-base font-semibold text-slate-800">WikiMind</span>
        </Link>

        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {user && (
          <div className="flex items-center gap-2 border-t border-slate-200 px-4 py-3">
            {user.avatar_url && (
              <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full" />
            )}
            <span className="truncate text-sm text-slate-600">{user.name || user.email}</span>
            <button
              type="button"
              onClick={() => {
                logout();
                window.location.href = "/login";
              }}
              className="ml-auto text-xs text-slate-400 hover:text-slate-700"
            >
              Logout
            </button>
          </div>
        )}

        <div className="border-t border-slate-200 px-4 py-3">
          <ConnectionIndicator state={wsState} />
        </div>
      </aside>

      <main className="relative flex-1 overflow-hidden">
        {children}

        <div className="pointer-events-none absolute right-4 top-4 flex w-80 flex-col gap-2">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`pointer-events-auto rounded-md border p-3 text-sm shadow-md ${
                toast.kind === "success"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : toast.kind === "error"
                    ? "border-rose-200 bg-rose-50 text-rose-900"
                    : "border-sky-200 bg-sky-50 text-sky-900"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">{toast.title}</div>
                  {toast.detail ? (
                    <div className="text-xs opacity-80">{toast.detail}</div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => dismissToast(toast.id)}
                  className="text-xs opacity-60 hover:opacity-100"
                  aria-label="Dismiss"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function ConnectionIndicator({ state }: { state: string }) {
  const tone =
    state === "open" ? "success" : state === "connecting" ? "info" : "warning";
  const label =
    state === "open"
      ? "Live"
      : state === "connecting"
        ? "Connecting"
        : "Offline";
  return (
    <div className="flex items-center justify-between text-xs text-slate-500">
      <span>Realtime</span>
      <Badge tone={tone}>{label}</Badge>
    </div>
  );
}
