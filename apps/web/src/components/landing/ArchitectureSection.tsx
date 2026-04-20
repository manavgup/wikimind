export function ArchitectureSection() {
  return (
    <section className="bg-slate-900 py-20 text-slate-100" id="architecture">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="mb-12">
          <div
            className="text-[11px] font-semibold uppercase text-brand-300"
            style={{ letterSpacing: "0.08em" }}
          >
            the three layers · in detail
          </div>
          <h2
            className="mt-3 font-bold text-white"
            style={{
              fontSize: "clamp(28px, 3.6vw, 42px)",
              lineHeight: "1.1",
              letterSpacing: "-0.02em",
              textWrap: "balance",
              maxWidth: "20ch",
            }}
          >
            Separate what the LLM owns from what you own.
          </h2>
          <p
            className="mt-4 text-[17px] text-slate-300"
            style={{ lineHeight: "1.55", maxWidth: "58ch", textWrap: "pretty" }}
          >
            Clear boundaries are the whole trick. Your sources are immutable. The wiki is
            LLM&#x2011;authored and versioned in git. The schema is a markdown file you edit
            together.
          </p>
        </div>

        <div className="mt-8 grid grid-cols-3 gap-4">
          {/* Layer 01 — Raw sources */}
          <div
            className="rounded-xl p-6"
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div
              className="text-[10px] uppercase text-brand-300"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: "0.1em",
              }}
            >
              Layer 01
            </div>
            <h3
              className="mt-2 mb-2 text-[20px] font-semibold text-white"
              style={{ letterSpacing: "-0.01em" }}
            >
              Raw sources
            </h3>
            <p className="mb-4 text-[13px] text-slate-400" style={{ lineHeight: "1.55" }}>
              Your curated collection — articles, papers, transcripts, images. The LLM reads from
              it, never modifies it. This is your source of truth.
            </p>
            <div
              className="rounded-md p-2.5 text-[11px]"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: "#64748b",
                background: "rgba(0,0,0,0.35)",
                border: "1px solid rgba(255,255,255,0.06)",
                lineHeight: "1.6",
              }}
            >
              <div>
                <span className="text-brand-300">raw/</span>
              </div>
              <div>├── articles/</div>
              <div>├── pdfs/</div>
              <div>├── transcripts/</div>
              <div>└── assets/</div>
            </div>
            <div
              className="mt-4 border-t pt-3 text-[11px] text-slate-400"
              style={{ borderTopColor: "rgba(255,255,255,0.1)" }}
            >
              <strong className="font-semibold text-white">Owner:</strong> you
            </div>
          </div>

          {/* Layer 02 — The wiki */}
          <div
            className="rounded-xl p-6"
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div
              className="text-[10px] uppercase text-brand-300"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: "0.1em",
              }}
            >
              Layer 02
            </div>
            <h3
              className="mt-2 mb-2 text-[20px] font-semibold text-white"
              style={{ letterSpacing: "-0.01em" }}
            >
              The wiki
            </h3>
            <p className="mb-4 text-[13px] text-slate-400" style={{ lineHeight: "1.55" }}>
              A directory of generated markdown. Entity pages, concept pages, comparisons, an index,
              a log. The LLM creates and maintains it as new sources arrive.
            </p>
            <div
              className="rounded-md p-2.5 text-[11px]"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: "#64748b",
                background: "rgba(0,0,0,0.35)",
                border: "1px solid rgba(255,255,255,0.06)",
                lineHeight: "1.6",
              }}
            >
              <div>
                <span className="text-brand-300">wiki/</span>
              </div>
              <div>
                ├── index.md{" "}
                <span style={{ color: "#475569" }}>// catalog</span>
              </div>
              <div>
                ├── log.md{" "}
                <span style={{ color: "#475569" }}>// timeline</span>
              </div>
              <div>├── concepts/</div>
              <div>└── entities/</div>
            </div>
            <div
              className="mt-4 border-t pt-3 text-[11px] text-slate-400"
              style={{ borderTopColor: "rgba(255,255,255,0.1)" }}
            >
              <strong className="font-semibold text-white">Owner:</strong> the LLM
            </div>
          </div>

          {/* Layer 03 — The schema */}
          <div
            className="rounded-xl p-6"
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div
              className="text-[10px] uppercase text-brand-300"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: "0.1em",
              }}
            >
              Layer 03
            </div>
            <h3
              className="mt-2 mb-2 text-[20px] font-semibold text-white"
              style={{ letterSpacing: "-0.01em" }}
            >
              The schema
            </h3>
            <p className="mb-4 text-[13px] text-slate-400" style={{ lineHeight: "1.55" }}>
              A single configuration file —{" "}
              <code
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "#9bb7d8",
                  fontSize: "12px",
                }}
              >
                CLAUDE.md
              </code>{" "}
              or{" "}
              <code
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "#9bb7d8",
                  fontSize: "12px",
                }}
              >
                AGENTS.md
              </code>
              . Describes conventions, workflows, and page formats.
            </p>
            <div
              className="rounded-md p-2.5 text-[11px]"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: "#64748b",
                background: "rgba(0,0,0,0.35)",
                border: "1px solid rgba(255,255,255,0.06)",
                lineHeight: "1.6",
              }}
            >
              <div>
                <span className="text-brand-300">AGENTS.md</span>
              </div>
              <div style={{ color: "#64748b" }}># how to ingest a source</div>
              <div style={{ color: "#64748b" }}># how to answer a query</div>
              <div style={{ color: "#64748b" }}># when to file back</div>
              <div style={{ color: "#64748b" }}># lint rules</div>
            </div>
            <div
              className="mt-4 border-t pt-3 text-[11px] text-slate-400"
              style={{ borderTopColor: "rgba(255,255,255,0.1)" }}
            >
              <strong className="font-semibold text-white">Owner:</strong> you and the LLM,
              together
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
