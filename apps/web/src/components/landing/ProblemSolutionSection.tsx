export function ProblemSolutionSection() {
  return (
    <section className="border-t border-zinc-900 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <h2 className="mb-12 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          Knowledge should compound, not scatter
        </h2>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Without */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 sm:p-8">
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-rose-900/40 text-sm text-rose-400">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </span>
              <h3 className="text-lg font-semibold text-zinc-300">Without WikiMind</h3>
            </div>
            <ul className="space-y-3 text-sm text-zinc-400">
              {[
                "Scattered bookmarks across browsers and devices",
                "Forgotten articles you saved but never revisited",
                "Information silos between PDFs, notes, and videos",
                "No way to cross-reference ideas from different sources",
                "Searching the internet again for things you already read",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <span className="mt-0.5 text-zinc-600">&mdash;</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* With */}
          <div className="rounded-xl border border-brand-800/30 bg-brand-900/10 p-6 sm:p-8">
            <div className="mb-4 flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-900/40 text-sm text-brand-400">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
              </span>
              <h3 className="text-lg font-semibold text-zinc-200">With WikiMind</h3>
            </div>
            <ul className="space-y-3 text-sm text-zinc-300">
              {[
                "Structured knowledge compiled from all your sources",
                "Cross-referenced concepts linked automatically by AI",
                "Instant answers grounded in your own collected material",
                "Contradiction detection across sources and time",
                "One searchable wiki that grows smarter as you feed it",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <span className="mt-0.5 text-brand-500">
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                    </svg>
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
