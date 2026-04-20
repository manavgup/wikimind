export function ProblemSolutionSection() {
  return (
    <section className="border-b border-slate-200 bg-slate-50 py-20" id="problem">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="mb-12">
          <div
            className="text-[11px] font-semibold uppercase text-brand-700"
            style={{ letterSpacing: "0.08em" }}
          >
            the gap
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
            RAG re&#x2011;discovers. WikiMind remembers.
          </h2>
          <p
            className="mt-4 text-[17px] text-slate-700"
            style={{ lineHeight: "1.55", maxWidth: "58ch", textWrap: "pretty" }}
          >
            Most LLM&#x2011;plus&#x2011;documents tools are a retrieval layer over raw files. Every
            question starts from scratch. Nothing accumulates. WikiMind flips the arrow: compile
            once, keep it current, and the LLM reads the <em>wiki</em> instead of the documents.
          </p>
        </div>

        {/* Two-column compare table */}
        <div className="grid overflow-hidden rounded-xl border border-slate-200 bg-white" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {/* Left — retrieval */}
          <div className="border-r border-slate-200 bg-slate-50 px-7 pt-7 pb-8">
            <h3
              className="mb-1.5 text-[11px] font-semibold uppercase text-slate-400"
              style={{ letterSpacing: "0.08em" }}
            >
              retrieval · the status quo
            </h3>
            <p
              className="mb-3.5 text-[22px] font-bold text-slate-900"
              style={{ lineHeight: "1.15", letterSpacing: "-0.015em" }}
            >
              Knowledge that evaporates between queries.
            </p>
            <ul className="m-0 list-none p-0">
              <CompareItem side="left">
                <strong className="font-semibold text-slate-900">Ephemeral.</strong> Every question
                re&#x2011;retrieves chunks from raw docs. Nothing is kept.
              </CompareItem>
              <CompareItem side="left" first={false}>
                <strong className="font-semibold text-slate-900">Flat.</strong> Cross&#x2011;references
                are re&#x2011;discovered on the fly — often imperfectly.
              </CompareItem>
              <CompareItem side="left" first={false}>
                <strong className="font-semibold text-slate-900">Opaque.</strong> You can&#x2019;t
                browse &#x201c;what the LLM knows&#x201d; — only watch it answer.
              </CompareItem>
              <CompareItem side="left" first={false}>
                <strong className="font-semibold text-slate-900">No synthesis.</strong> Questions
                spanning five documents get re&#x2011;solved every time.
              </CompareItem>
            </ul>
          </div>

          {/* Right — compilation */}
          <div className="bg-brand-50 px-7 pt-7 pb-8">
            <h3
              className="mb-1.5 text-[11px] font-semibold uppercase text-brand-700"
              style={{ letterSpacing: "0.08em" }}
            >
              compilation · WikiMind
            </h3>
            <p
              className="mb-3.5 text-[22px] font-bold text-slate-900"
              style={{ lineHeight: "1.15", letterSpacing: "-0.015em" }}
            >
              A compounding artifact you can actually read.
            </p>
            <ul className="m-0 list-none p-0">
              <CompareItem side="right">
                <strong className="font-semibold text-slate-900">Persistent.</strong> Every source
                is compiled into markdown pages you can browse.
              </CompareItem>
              <CompareItem side="right" first={false}>
                <strong className="font-semibold text-slate-900">Linked.</strong> Cross&#x2011;references
                are <em>already there</em>. Backlinks, graph view, concept trees.
              </CompareItem>
              <CompareItem side="right" first={false}>
                <strong className="font-semibold text-slate-900">Inspectable.</strong> Every claim
                carries a confidence tag: <em>sourced · mixed · inferred · opinion</em>.
              </CompareItem>
              <CompareItem side="right" first={false}>
                <strong className="font-semibold text-slate-900">Cumulative.</strong> Synthesis
                happens once at compile&#x2011;time, then gets revised — not re&#x2011;derived.
              </CompareItem>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

function CompareItem({
  children,
  side,
  first = true,
}: {
  children: React.ReactNode;
  side: "left" | "right";
  first?: boolean;
}) {
  const borderColor = side === "left" ? "border-slate-200" : "border-brand-100";
  const lineColor = side === "left" ? "bg-slate-300" : "bg-brand-300";
  return (
    <li
      className={`relative py-2.5 pl-[26px] text-[14px] text-slate-700 ${
        first ? "" : `border-t ${borderColor}`
      }`}
      style={{ lineHeight: "1.55" }}
    >
      <span
        className={`absolute left-0 top-[19px] h-[1px] w-4 ${lineColor}`}
      />
      {children}
    </li>
  );
}
