export function MemexSection() {
  return (
    <section className="border-b border-slate-200 bg-slate-50 py-20" id="memex">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="grid items-start gap-16" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
          {/* Left — text */}
          <div>
            <div
              className="text-[11px] font-semibold uppercase text-brand-700"
              style={{ letterSpacing: "0.08em" }}
            >
              the lineage
            </div>
            <h2
              className="mt-3 font-bold text-slate-900"
              style={{
                fontSize: "clamp(28px, 3.6vw, 42px)",
                lineHeight: "1.1",
                letterSpacing: "-0.02em",
                textWrap: "balance",
                maxWidth: "18ch",
              }}
            >
              A Memex that maintains itself.
            </h2>
            <p className="mt-5 text-[16px] text-slate-700" style={{ lineHeight: "1.65", maxWidth: "58ch" }}>
              In 1945 Vannevar Bush described the Memex — a personal, curated store of documents
              linked by associative trails. Private. Actively maintained. With the connections
              between documents as valuable as the documents themselves.
            </p>
            <p className="text-[16px] text-slate-700" style={{ lineHeight: "1.65", maxWidth: "58ch" }}>
              The part he couldn&#x2019;t solve was{" "}
              <em>who does the maintenance.</em> Wikis answered it with volunteers, and fizzled at
              personal scale. WikiMind answers it differently: the LLM does it. The cost of upkeep
              falls to near zero. The wiki stays alive.
            </p>
            <p
              className="mt-6 text-[13px] text-slate-400"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              → bush, 1945 · &#x201c;as we may think&#x201d; · atlantic monthly
            </p>
          </div>

          {/* Right — knowledge graph SVG */}
          <div>
            <svg
              viewBox="0 0 420 340"
              xmlns="http://www.w3.org/2000/svg"
              className="block w-full"
              style={{
                height: "auto",
                border: "1px solid #e2e8f0",
                borderRadius: "12px",
                background: "#fff",
                padding: "12px",
                boxShadow: "0 1px 2px 0 rgb(0 0 0 / 0.04)",
              }}
              aria-label="Knowledge graph sketch"
            >
              <defs>
                <marker
                  id="arr"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L10,5 L0,10 Z" fill="#cbd5e1" />
                </marker>
              </defs>
              {/* Edges */}
              <g stroke="#cbd5e1" strokeWidth="1" fill="none">
                <line x1="110" y1="90" x2="210" y2="70" />
                <line x1="210" y1="70" x2="320" y2="110" />
                <line x1="210" y1="70" x2="170" y2="180" />
                <line x1="170" y1="180" x2="80" y2="230" />
                <line x1="170" y1="180" x2="290" y2="200" />
                <line x1="290" y1="200" x2="320" y2="110" />
                <line x1="290" y1="200" x2="340" y2="280" />
                <line x1="80" y1="230" x2="150" y2="290" />
                <line x1="150" y1="290" x2="280" y2="300" />
                <line x1="280" y1="300" x2="340" y2="280" />
                <line x1="110" y1="90" x2="170" y2="180" />
              </g>
              {/* Nodes */}
              <g fontFamily="Inter, sans-serif" fontSize="11" fill="#1e293b">
                <g>
                  <circle cx="110" cy="90" r="22" fill="#e6eef7" stroke="#9bb7d8" />
                  <text x="110" y="94" textAnchor="middle">
                    Rust
                  </text>
                </g>
                <g>
                  <circle cx="210" cy="70" r="26" fill="#4673ad" stroke="#2b4876" />
                  <text x="210" y="74" textAnchor="middle" fill="#fff" fontWeight="600">
                    Borrow checker
                  </text>
                </g>
                <g>
                  <circle cx="320" cy="110" r="20" fill="#fff" stroke="#cbd5e1" />
                  <text x="320" y="114" textAnchor="middle">
                    Send/Sync
                  </text>
                </g>
                <g>
                  <circle cx="170" cy="180" r="24" fill="#e6eef7" stroke="#9bb7d8" />
                  <text x="170" y="184" textAnchor="middle">
                    Concurrency
                  </text>
                </g>
                <g>
                  <circle cx="80" cy="230" r="18" fill="#fff" stroke="#cbd5e1" />
                  <text x="80" y="234" textAnchor="middle">
                    Raft
                  </text>
                </g>
                <g>
                  <circle cx="290" cy="200" r="20" fill="#fff" stroke="#cbd5e1" />
                  <text x="290" y="204" textAnchor="middle">
                    Arc/Mutex
                  </text>
                </g>
                <g>
                  <circle cx="150" cy="290" r="18" fill="#fff" stroke="#cbd5e1" />
                  <text x="150" y="294" textAnchor="middle">
                    Paxos
                  </text>
                </g>
                <g>
                  <circle cx="280" cy="300" r="20" fill="#fff" stroke="#cbd5e1" />
                  <text x="280" y="304" textAnchor="middle">
                    Data race
                  </text>
                </g>
                <g>
                  <circle cx="340" cy="280" r="16" fill="#fff" stroke="#cbd5e1" />
                  <text x="340" y="284" textAnchor="middle">
                    RAII
                  </text>
                </g>
              </g>
              {/* Caption */}
              <text
                x="210"
                y="328"
                textAnchor="middle"
                fontFamily="Inter, sans-serif"
                fontSize="10"
                fill="#94a3b8"
                letterSpacing="1"
              >
                KNOWLEDGE GRAPH · LIVE VIEW
              </text>
            </svg>
          </div>
        </div>
      </div>
    </section>
  );
}
