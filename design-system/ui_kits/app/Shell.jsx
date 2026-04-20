/* global React */
const { useState } = React;

const NAV_ITEMS = [
  { key: "inbox",    label: "Inbox",    icon: "📥" },
  { key: "ask",      label: "Ask",      icon: "💬" },
  { key: "wiki",     label: "Wiki",     icon: "📚" },
  { key: "graph",    label: "Graph",    icon: "🕸️" },
  { key: "health",   label: "Health",   icon: "🩺" },
  { key: "settings", label: "Settings", icon: "⚙️" },
];

function Shell({ current, onNavigate, children, toasts, onDismissToast }) {
  return (
    <div className="flex h-screen w-screen bg-slate-50 text-slate-900 antialiased">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-5">
          <span className="text-xl">🧠</span>
          <span className="text-base font-semibold text-slate-800">WikiMind</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV_ITEMS.map((item) => (
            <button key={item.key} type="button" onClick={() => onNavigate(item.key)}
              className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition text-left ${
                current === item.key
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-600 hover:bg-slate-100"
              }`}>
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-2 border-t border-slate-200 px-4 py-3">
          <div className="h-7 w-7 shrink-0 rounded-full bg-gradient-to-br from-brand-300 to-brand-500 flex items-center justify-center text-white text-xs font-semibold">M</div>
          <span className="truncate text-sm text-slate-600">manav@wikimind.ai</span>
        </div>
        <div className="border-t border-slate-200 px-4 py-3">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Realtime</span>
            <Badge tone="success">Live</Badge>
          </div>
        </div>
      </aside>

      <main className="relative flex-1 overflow-hidden">
        {children}

        {/* Toasts */}
        <div className="pointer-events-none absolute right-4 top-4 flex w-80 flex-col gap-2">
          {toasts.map((t) => (
            <div key={t.id}
              className={`pointer-events-auto rounded-md border p-3 text-sm shadow-md ${
                t.kind === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : t.kind === "error" ? "border-rose-200 bg-rose-50 text-rose-900"
                  : "border-sky-200 bg-sky-50 text-sky-900"
              }`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">{t.title}</div>
                  {t.detail && <div className="text-xs opacity-80">{t.detail}</div>}
                </div>
                <button type="button" onClick={() => onDismissToast(t.id)}
                  className="text-xs opacity-60 hover:opacity-100" aria-label="Dismiss">✕</button>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

/* Header shared by views */
function ViewHeader({ title, subtitle, right }) {
  return (
    <header className="border-b border-slate-200 bg-white px-6 py-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {right}
      </div>
    </header>
  );
}

/* Stub view for graph / health / settings */
function StubView({ title, icon }) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <ViewHeader title={title} subtitle="Not included in this UI kit pass." />
      <div className="flex flex-1 items-center justify-center">
        <div className="text-center">
          <div className="text-4xl">{icon}</div>
          <div className="mt-3 text-sm text-slate-500">See the real view in <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">apps/web/src/components/</code></div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Shell, ViewHeader, StubView });
