const CASES = [
  {
    eye: "personal",
    title: "Self\u2011knowledge",
    description:
      "Journal entries, podcast notes, health logs. Over months, a structured picture of yourself compounds \u2014 goals, psychology, patterns.",
    tags: ["journal", "health", "habits"],
  },
  {
    eye: "research",
    title: "Topic deep\u2011dive",
    description:
      "Go deep on a subject over weeks \u2014 papers, reports, blog posts. The wiki becomes the running thesis. New evidence updates older claims.",
    tags: ["papers", "thesis", "citations"],
  },
  {
    eye: "reading",
    title: "Book companion",
    description:
      "Feed each chapter as you go. Pages accrue for characters, places, arcs, themes. By the last chapter you\u2019ve built a Tolkien\u2011gateway\u2011style fan wiki of one.",
    tags: ["chapters", "characters", "themes"],
  },
  {
    eye: "team",
    title: "Team memory",
    description:
      "Feed Slack threads, meeting transcripts, customer calls. The wiki stays current because the LLM does the maintenance nobody else wants to do.",
    tags: ["slack", "meetings", "decisions"],
  },
  {
    eye: "work",
    title: "Due diligence",
    description:
      "Competitive analysis, M&A evaluation, market landscape. Structured rather than scattered across a dozen Google Docs.",
    tags: ["competitors", "markets", "sources"],
  },
  {
    eye: "play",
    title: "Hobby archives",
    description:
      "Trip planning, course notes, a long hobby deep\u2011dive. Anything accumulating over time that deserves more than a Notes app.",
    tags: ["trips", "courses", "hobbies"],
  },
];

export function UseCasesSection() {
  return (
    <section className="border-b border-slate-200 py-20" id="cases">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="mb-12">
          <div
            className="text-[11px] font-semibold uppercase text-brand-700"
            style={{ letterSpacing: "0.08em" }}
          >
            where it helps
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
            Anywhere knowledge accumulates over time.
          </h2>
          <p
            className="mt-4 text-[17px] text-slate-700"
            style={{ lineHeight: "1.55", maxWidth: "58ch", textWrap: "pretty" }}
          >
            WikiMind works wherever you&#x2019;re building up a body of understanding across many
            sources — personal, academic, professional.
          </p>
        </div>

        {/* 3-column grid with 1px gap lines */}
        <div
          className="grid overflow-hidden rounded-xl border border-slate-200"
          style={{
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "1px",
            background: "#e2e8f0",
          }}
        >
          {CASES.map((c) => (
            <div
              key={c.title}
              className="flex flex-col gap-2.5 bg-white p-6"
              style={{ minHeight: "180px" }}
            >
              <div
                className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase text-brand-700"
                style={{ letterSpacing: "0.08em" }}
              >
                {c.eye}
              </div>
              <h3
                className="m-0 text-[18px] font-semibold text-slate-900"
                style={{ letterSpacing: "-0.01em" }}
              >
                {c.title}
              </h3>
              <p className="m-0 text-[13px] text-slate-700" style={{ lineHeight: "1.55" }}>
                {c.description}
              </p>
              <div className="mt-auto flex flex-wrap gap-1">
                {c.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-[3px] border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
