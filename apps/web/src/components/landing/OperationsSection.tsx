export function OperationsSection() {
  return (
    <section className="border-b border-slate-200 py-20" id="how">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="mb-12">
          <div
            className="text-[11px] font-semibold uppercase text-brand-700"
            style={{ letterSpacing: "0.08em" }}
          >
            three operations
          </div>
          <h2
            className="mt-3 font-bold text-slate-900"
            style={{
              fontSize: "clamp(28px, 3.6vw, 42px)",
              lineHeight: "1.1",
              letterSpacing: "-0.02em",
              textWrap: "balance",
              maxWidth: "20ch",
            }}
          >
            Feed. Ask. Lint.
          </h2>
          <p
            className="mt-4 text-[17px] text-slate-700"
            style={{ lineHeight: "1.55", maxWidth: "58ch", textWrap: "pretty" }}
          >
            Everything you do with WikiMind falls into one of three verbs. The first adds to the
            wiki. The second queries it. The third keeps it healthy.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-4">
          {/* FEED */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 transition-colors duration-[180ms] hover:border-brand-300">
            <div
              className="text-[11px] font-semibold text-brand-600"
              style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em" }}
            >
              01 / INGEST
            </div>
            <h3
              className="mt-1.5 mb-2 text-[22px] font-bold text-slate-900"
              style={{ letterSpacing: "-0.015em" }}
            >
              Feed
            </h3>
            <p className="mb-4 text-[14px] text-slate-700" style={{ lineHeight: "1.55" }}>
              Drop a URL, PDF, YouTube link, or podcast into the Inbox. The LLM reads it, discusses
              key takeaways with you, writes a summary page, and updates 10–15 existing pages where
              it matters.
            </p>

            {/* Mini preview */}
            <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">
                  PDF
                </span>
                <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                  <span className="inline-block h-[9px] w-[9px] rounded-full border-2 border-slate-200 animate-spin-custom" style={{ borderTopColor: "#0369a1" }} />
                  Processing
                </span>
              </div>
              <div className="mt-2 text-[13px] font-semibold leading-snug text-slate-900">
                Attention Is All You Need
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                arxiv.org/abs/1706.03762 · extracting concepts…
              </div>
            </div>

            {/* Spec footer */}
            <div className="mt-5 border-t border-slate-200 pt-4 text-[12px] text-slate-500">
              <strong className="text-slate-900">A single source</strong> touches 10–15 wiki pages ·
              updates the index · appends the log.
            </div>
          </div>

          {/* ASK */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 transition-colors duration-[180ms] hover:border-brand-300">
            <div
              className="text-[11px] font-semibold text-brand-600"
              style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em" }}
            >
              02 / QUERY
            </div>
            <h3
              className="mt-1.5 mb-2 text-[22px] font-bold text-slate-900"
              style={{ letterSpacing: "-0.015em" }}
            >
              Ask
            </h3>
            <p className="mb-4 text-[14px] text-slate-700" style={{ lineHeight: "1.55" }}>
              Ask anything. The LLM reads the wiki (not the raw docs), synthesises an answer, and
              shows every supporting source. Good answers can be <em>filed back</em> as their own
              wiki pages.
            </p>

            {/* Mini preview */}
            <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
              <div
                className="text-[11px] font-medium uppercase text-slate-400"
                style={{ letterSpacing: "0.04em" }}
              >
                Q1
              </div>
              <div className="mt-2 text-[13px] font-semibold leading-snug text-slate-900">
                How does the borrow checker prevent data races?
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700">
                  Rust ownership
                </span>
                <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-700">
                  Fearless concurrency
                </span>
              </div>
            </div>

            {/* Spec footer */}
            <div className="mt-5 border-t border-slate-200 pt-4 text-[12px] text-slate-500">
              <strong className="text-slate-900">File back</strong> turns a good answer into a
              permanent wiki page, citations and all.
            </div>
          </div>

          {/* LINT */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 transition-colors duration-[180ms] hover:border-brand-300">
            <div
              className="text-[11px] font-semibold text-brand-600"
              style={{ fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.04em" }}
            >
              03 / HEALTH
            </div>
            <h3
              className="mt-1.5 mb-2 text-[22px] font-bold text-slate-900"
              style={{ letterSpacing: "-0.015em" }}
            >
              Lint
            </h3>
            <p className="mb-4 text-[14px] text-slate-700" style={{ lineHeight: "1.55" }}>
              Ask the LLM to health&#x2011;check the wiki. It flags contradictions between pages,
              orphan entries, stale claims, and missing concepts — and suggests new questions worth
              asking.
            </p>

            {/* Mini preview */}
            <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                  82% healthy
                </span>
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                  3 contradictions
                </span>
                <span className="rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                  7 orphans
                </span>
              </div>
              <div className="mt-2.5 text-[13px] font-semibold leading-snug text-slate-900">
                &#x201c;Raft&#x201d; and &#x201c;Paxos complexity&#x201d;
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                contradiction · last updated 11 days ago
              </div>
            </div>

            {/* Spec footer */}
            <div className="mt-5 border-t border-slate-200 pt-4 text-[12px] text-slate-500">
              <strong className="text-slate-900">No one wants</strong> this job. The LLM does it
              without forgetting or getting bored.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
