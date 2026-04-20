const OPERATIONS = [
  {
    title: "Feed",
    description:
      "Ingest any source: URLs, PDFs, YouTube transcripts, plain text. Drop it in and the compiler handles the rest. One-click ingestion into your knowledge graph.",
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
        />
      </svg>
    ),
    color: "text-sky-400",
    bgColor: "bg-sky-900/20 border-sky-800/30",
    visual: (
      <div className="mt-4 space-y-2 rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs text-zinc-500">
        <div className="text-sky-400">$ wikimind ingest</div>
        <div>
          <span className="text-zinc-600">source:</span> arxiv.org/abs/2301.00001
        </div>
        <div>
          <span className="text-zinc-600">type:</span>{" "}
          <span className="text-zinc-400">url/pdf</span>
        </div>
        <div>
          <span className="text-zinc-600">status:</span>{" "}
          <span className="text-emerald-500">compiled</span>
        </div>
      </div>
    ),
  },
  {
    title: "Ask",
    description:
      "Chat with your knowledge base. The AI answers from YOUR compiled wiki, not the internet. Every answer is grounded in sources you trust.",
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"
        />
      </svg>
    ),
    color: "text-brand-400",
    bgColor: "bg-brand-900/20 border-brand-800/30",
    visual: (
      <div className="mt-4 space-y-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs">
        <div className="flex gap-2">
          <span className="shrink-0 text-zinc-600">Q:</span>
          <span className="text-zinc-300">How do transformers handle long-range dependencies?</span>
        </div>
        <div className="flex gap-2">
          <span className="shrink-0 text-zinc-600">A:</span>
          <span className="text-zinc-400">
            According to your wiki article on Attention Mechanisms,
            self-attention computes pairwise scores across all positions...
          </span>
        </div>
      </div>
    ),
  },
  {
    title: "Lint",
    description:
      "Automatic contradiction detection across sources. Find conflicts in your knowledge before they become blind spots. The compiler flags disagreements.",
    icon: (
      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
        />
      </svg>
    ),
    color: "text-amber-400",
    bgColor: "bg-amber-900/20 border-amber-800/30",
    visual: (
      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-xs">
        <div className="mb-2 flex items-center gap-2 text-amber-400">
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
            />
          </svg>
          Contradiction detected
        </div>
        <div className="space-y-1 text-zinc-500">
          <div>
            <span className="text-zinc-400">Source A</span> claims dropout rate of 0.1
          </div>
          <div>
            <span className="text-zinc-400">Source B</span> claims dropout rate of 0.3
          </div>
        </div>
      </div>
    ),
  },
];

export function OperationsSection() {
  return (
    <section className="border-t border-zinc-900 bg-zinc-950/50 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-4 text-center text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Three operations
        </div>
        <h2 className="mb-12 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          Feed. Ask. Lint.
        </h2>

        <div className="grid gap-6 md:grid-cols-3">
          {OPERATIONS.map((op) => (
            <div
              key={op.title}
              className={`rounded-xl border p-6 transition hover:border-zinc-700 ${op.bgColor}`}
            >
              <div className={`mb-3 ${op.color}`}>{op.icon}</div>
              <h3 className="mb-2 text-lg font-semibold text-zinc-100">{op.title}</h3>
              <p className="text-sm leading-relaxed text-zinc-400">{op.description}</p>
              {op.visual}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
