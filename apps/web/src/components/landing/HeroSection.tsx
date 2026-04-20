interface HeroSectionProps {
  onSignIn: () => void;
}

export function HeroSection({ onSignIn }: HeroSectionProps) {
  return (
    <header className="border-b border-slate-200 py-[80px] pb-[64px]" id="top">
      <div className="mx-auto max-w-[1120px] px-8">
        <div
          className="mt-[56px] grid items-start gap-12"
          style={{ gridTemplateColumns: "minmax(0, 1.15fr) minmax(0, 1fr)" }}
        >
          {/* Left column */}
          <div>
            <span
              className="inline-flex items-center gap-2 rounded-full border border-brand-100 bg-brand-50 px-2.5 py-[5px] text-[11px] font-semibold uppercase text-brand-700"
              style={{ letterSpacing: "0.08em" }}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
              v0.4 · the LLM maintains it
            </span>

            <h1
              className="mt-6 font-bold text-slate-900"
              style={{
                fontSize: "clamp(40px, 6.4vw, 76px)",
                lineHeight: "1.02",
                letterSpacing: "-0.025em",
                textWrap: "balance",
                maxWidth: "14ch",
              }}
            >
              you never write the wiki.
              <br />
              you <em className="font-serif-italic font-normal text-brand-700">feed</em> it.
            </h1>

            <p
              className="mt-6 text-[19px] text-slate-700"
              style={{ lineHeight: "1.55", maxWidth: "58ch", textWrap: "pretty" }}
            >
              WikiMind is a personal knowledge OS. Drop in articles, papers, PDFs, YouTube links,
              or podcasts — an LLM compiles them into a living, cross&#x2011;linked wiki that keeps
              getting richer as you read. Ask anything. File good answers back.
            </p>

            <div className="mt-8 flex flex-wrap gap-3 text-[13px] text-slate-500">
              <span className="neg-mark inline-flex items-center">not a note app</span>
              <span className="text-slate-300 mx-0.5">·</span>
              <span className="neg-mark inline-flex items-center">not a chatbot</span>
              <span className="text-slate-300 mx-0.5">·</span>
              <span className="neg-mark inline-flex items-center">not a RAG tool</span>
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={onSignIn}
                className="inline-flex items-center gap-1.5 rounded-md border border-transparent bg-brand-700 px-[18px] py-2.5 text-[14px] font-medium text-white transition-colors duration-100 hover:bg-brand-800"
              >
                Open the wiki
                <span className="transition-transform duration-100 group-hover:translate-x-0.5">
                  →
                </span>
              </button>
              <a
                href="#how"
                className="inline-flex items-center rounded-md border border-slate-300 bg-white px-[18px] py-2.5 text-[14px] font-medium text-slate-700 transition-colors duration-100 hover:border-brand-300 hover:text-slate-900"
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById("how")?.scrollIntoView({ behavior: "smooth" });
                }}
              >
                See how it works
              </a>
            </div>

            <div className="mt-8 flex flex-wrap gap-6 text-[12px] text-slate-500">
              <div className="flex items-center gap-1.5">
                local&#x2011;first · your data stays on disk
              </div>
              <div className="flex items-center gap-1.5">
                bring your own LLM ·{" "}
                <code
                  className="rounded bg-slate-100 px-1.5 py-[1px] text-[11px] text-slate-900"
                  style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
                >
                  GPT
                </code>{" "}
                <code
                  className="rounded bg-slate-100 px-1.5 py-[1px] text-[11px] text-slate-900"
                  style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
                >
                  Claude
                </code>{" "}
                <code
                  className="rounded bg-slate-100 px-1.5 py-[1px] text-[11px] text-slate-900"
                  style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
                >
                  Ollama
                </code>
              </div>
            </div>
          </div>

          {/* Right column — three-layer architecture diagram */}
          <div
            className="rounded-xl border border-slate-200 bg-white p-4"
            style={{ boxShadow: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 4px 16px -8px rgb(31 50 81 / 0.10)" }}
            aria-label="Three layers of WikiMind"
          >
            {/* Diagram header */}
            <div className="flex items-center justify-between border-b border-slate-200 px-1 pb-3.5">
              <span
                className="text-[11px] font-medium uppercase text-slate-400"
                style={{ letterSpacing: "0.04em" }}
              >
                Architecture · three layers
              </span>
              <span className="flex gap-1.5">
                <span className="h-[9px] w-[9px] rounded-full bg-slate-200" />
                <span className="h-[9px] w-[9px] rounded-full bg-slate-200" />
                <span className="h-[9px] w-[9px] rounded-full bg-slate-200" />
              </span>
            </div>

            {/* Layer stack */}
            <div className="flex flex-col gap-2.5 px-1 pt-4 pb-1">
              {/* Layer 01 — Raw sources */}
              <div className="flex items-center gap-3.5 rounded-lg border border-slate-200 bg-white px-4 py-3.5">
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-slate-100 text-[10px] font-semibold text-slate-600"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  01
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold leading-snug text-slate-900">
                    Raw sources
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500" style={{ lineHeight: "1.45" }}>
                    PDFs, URLs, videos, transcripts. Immutable. Never modified.
                  </div>
                </div>
                <span
                  className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
                  style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.02em" }}
                >
                  you own
                </span>
              </div>

              {/* Arrow */}
              <div className="-my-1 flex items-center justify-center text-slate-300">
                <svg width="12" height="16" viewBox="0 0 12 16" fill="none">
                  <path
                    d="M6 1v12m-4-4l4 4 4-4"
                    stroke="currentColor"
                    strokeWidth="1.25"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* Layer 02 — The wiki */}
              <div className="flex items-center gap-3.5 rounded-lg border border-brand-100 bg-brand-50 px-4 py-3.5">
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-100 text-[10px] font-semibold text-brand-700"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  02
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold leading-snug text-slate-900">
                    The wiki · the compounding artifact
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500" style={{ lineHeight: "1.45" }}>
                    Markdown pages: summaries, entities, concepts, comparisons. Rewritten with every
                    ingest.
                  </div>
                </div>
                <span
                  className="rounded border border-brand-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-brand-700"
                  style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.02em" }}
                >
                  LLM owns
                </span>
              </div>

              {/* Arrow */}
              <div className="-my-1 flex items-center justify-center text-slate-300">
                <svg width="12" height="16" viewBox="0 0 12 16" fill="none">
                  <path
                    d="M6 1v12m-4-4l4 4 4-4"
                    stroke="currentColor"
                    strokeWidth="1.25"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* Layer 03 — The schema */}
              <div className="flex items-center gap-3.5 rounded-lg border border-slate-200 bg-white px-4 py-3.5">
                <span
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-slate-100 text-[10px] font-semibold text-slate-600"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  03
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold leading-snug text-slate-900">
                    The schema
                  </div>
                  <div className="mt-0.5 text-[12px] text-slate-500" style={{ lineHeight: "1.45" }}>
                    A{" "}
                    <code
                      className="rounded bg-slate-100 px-[5px] py-[1px] text-[11px] text-slate-900"
                      style={{ fontFamily: "'JetBrains Mono', monospace" }}
                    >
                      CLAUDE.md
                    </code>{" "}
                    that tells the LLM how your wiki is organised. You co&#x2011;evolve it.
                  </div>
                </div>
                <span
                  className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
                  style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.02em" }}
                >
                  co&#x2011;owned
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
