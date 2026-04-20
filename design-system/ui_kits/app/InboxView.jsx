/* global React */
const { useState, useCallback } = React;

const INITIAL_SOURCES = [
  { id: "s1", type: "pdf", title: "Attention Is All You Need", url: "arxiv.org/abs/1706.03762", status: "compiled", ts: "Apr 17, 9:12" },
  { id: "s2", type: "url", title: "Designing Data-Intensive Applications — Ch. 9", url: "dataintensive.net/ch09", status: "processing", ts: "Apr 18, 10:42", progress: "Extracting concepts…" },
  { id: "s3", type: "youtube", title: "Rust ownership explained (Jon Gjengset)", url: "youtube.com/watch?v=8M0QfLUDaaA", status: "compiled", ts: "Apr 15, 18:31" },
  { id: "s4", type: "url", title: "Why FoundationDB is the best database", url: "apple.com/foundationdb-blog", status: "failed", ts: "Apr 14, 22:05", error: "403 — source URL is paywalled" },
  { id: "s5", type: "text", title: "Meeting notes — roadmap Q2", url: null, status: "compiled", ts: "Apr 12, 14:00" },
];

const TYPE_LABEL = { url: "URL", pdf: "PDF", youtube: "YouTube", audio: "Audio", text: "Note", rss: "RSS", email: "Email", obsidian: "Obsidian" };
const STATUS_TONE = { pending: "neutral", processing: "info", compiled: "success", failed: "danger" };
const STATUS_LABEL = { pending: "Pending", processing: "Processing", compiled: "Done", failed: "Failed" };

function QuickAddBar({ onSubmitUrl }) {
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    await onSubmitUrl(url.trim());
    setUrl("");
    setBusy(false);
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:flex-row md:items-stretch">
      <form onSubmit={submit} className="flex flex-1 items-center gap-2">
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste a URL (article, YouTube, RSS feed)..."
          className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
        <Button type="submit" disabled={busy || !url.trim()}>
          {busy && <Spinner size={12} />}
          Add
        </Button>
      </form>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => { e.preventDefault(); setDragActive(false); }}
        className={`flex flex-1 items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-2 text-xs transition ${
          dragActive ? "border-brand-400 bg-brand-50 text-brand-700" : "border-slate-300 text-slate-500"
        }`}>
        <span aria-hidden>📄</span>
        <span>Drop PDF here, or</span>
        <label className="cursor-pointer font-semibold text-brand-600 hover:underline">
          browse
          <input type="file" accept="application/pdf" className="hidden" />
        </label>
      </div>
    </div>
  );
}

function SourceCard({ source, onRetry }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge tone="brand">{TYPE_LABEL[source.type]}</Badge>
            <Badge tone={STATUS_TONE[source.status]}>
              {source.status === "processing"
                ? <><Spinner size={10} /> {STATUS_LABEL[source.status]}</>
                : STATUS_LABEL[source.status]}
            </Badge>
          </div>
          <h3 className="mt-2 truncate text-sm font-semibold text-slate-900">{source.title}</h3>
          {source.url && (
            <a href="#" onClick={(e) => e.preventDefault()}
              className="mt-0.5 block truncate text-xs text-brand-600 hover:underline">
              {source.url}
            </a>
          )}
        </div>
        <div className="shrink-0 text-right text-xs text-slate-400">{source.ts}</div>
      </div>
      {source.status === "processing" && source.progress && (
        <p className="mt-2 text-xs text-slate-500">{source.progress}</p>
      )}
      {source.status === "failed" && (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-rose-700">{source.error}</p>
          <Button size="sm" variant="secondary" onClick={() => onRetry(source.id)}>Retry compile</Button>
        </div>
      )}
    </Card>
  );
}

function InboxView({ pushToast }) {
  const [sources, setSources] = useState(INITIAL_SOURCES);

  const addUrl = async (url) => {
    const id = "s" + Date.now();
    const isYt = /youtube\.com|youtu\.be/.test(url);
    const newSource = {
      id, type: isYt ? "youtube" : "url", title: url.replace(/^https?:\/\//, "").slice(0, 60),
      url, status: "processing", ts: "Just now", progress: "Fetching page…",
    };
    setSources((xs) => [newSource, ...xs]);

    // Fake compile pipeline
    setTimeout(() => setSources((xs) => xs.map(s => s.id === id ? { ...s, progress: "Extracting concepts…" } : s)), 900);
    setTimeout(() => {
      setSources((xs) => xs.map(s => s.id === id ? { ...s, status: "compiled", progress: undefined } : s));
      pushToast({ kind: "success", title: "Compiled new article", detail: newSource.title });
    }, 2200);
  };

  const retry = (id) => {
    setSources((xs) => xs.map(s => s.id === id ? { ...s, status: "processing", progress: "Retrying…", error: undefined } : s));
    setTimeout(() => setSources((xs) => xs.map(s => s.id === id ? { ...s, status: "compiled", progress: undefined } : s)), 1500);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <ViewHeader
        title="Inbox"
        subtitle="All ingested sources. Live progress streams over WebSocket (connected)."
        right={<div className="text-xs text-slate-500">{sources.length} source{sources.length === 1 ? "" : "s"}</div>}
      />
      <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-6">
        <QuickAddBar onSubmitUrl={addUrl} />
        <div className="flex flex-col gap-3">
          {sources.map((s) => <SourceCard key={s.id} source={s} onRetry={retry} />)}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { InboxView });
