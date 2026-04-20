const PIPELINE_STAGES = [
  {
    label: "Ingest",
    description: "URL, PDF, YouTube, text",
    color: "border-sky-800/40 text-sky-400",
  },
  {
    label: "Normalize",
    description: "Extract & clean content",
    color: "border-violet-800/40 text-violet-400",
  },
  {
    label: "Compile",
    description: "LLM-powered synthesis",
    color: "border-brand-800/40 text-brand-400",
  },
  {
    label: "Index",
    description: "Embed & store vectors",
    color: "border-amber-800/40 text-amber-400",
  },
  {
    label: "Search",
    description: "Hybrid keyword + semantic",
    color: "border-emerald-800/40 text-emerald-400",
  },
];

const TECH_STACK = [
  { label: "FastAPI", detail: "Async Python gateway" },
  { label: "SQLite / Postgres", detail: "Relational storage" },
  { label: "ChromaDB", detail: "Vector embeddings" },
  { label: "Multi-LLM", detail: "OpenAI, Anthropic, local" },
];

export function ArchitectureSection() {
  return (
    <section className="border-t border-zinc-900 bg-zinc-900/40 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-4 text-center text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Under the hood
        </div>
        <h2 className="mb-12 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          Architecture
        </h2>

        {/* Pipeline */}
        <div className="mb-12 rounded-xl border border-zinc-800 bg-zinc-950/80 p-6 sm:p-8">
          <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
            {PIPELINE_STAGES.map((stage, i) => (
              <div key={stage.label} className="flex flex-1 items-center gap-3">
                <div
                  className={`flex-1 rounded-lg border bg-zinc-900 p-3 text-center ${stage.color}`}
                >
                  <div className="text-sm font-semibold">{stage.label}</div>
                  <div className="mt-0.5 text-xs text-zinc-500">{stage.description}</div>
                </div>
                {i < PIPELINE_STAGES.length - 1 && (
                  <svg
                    className="hidden h-4 w-4 shrink-0 text-zinc-700 sm:block"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="m8.25 4.5 7.5 7.5-7.5 7.5"
                    />
                  </svg>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Tech stack */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {TECH_STACK.map((tech) => (
            <div
              key={tech.label}
              className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 text-center"
            >
              <div className="font-mono text-sm font-semibold text-zinc-300">{tech.label}</div>
              <div className="mt-1 text-xs text-zinc-500">{tech.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
