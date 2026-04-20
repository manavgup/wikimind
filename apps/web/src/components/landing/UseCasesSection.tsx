const USE_CASES = [
  {
    title: "Research & Academia",
    description:
      "Compile papers into a personal knowledge base. Cross-reference findings across dozens of sources without losing track.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342"
        />
      </svg>
    ),
  },
  {
    title: "Engineering Teams",
    description:
      "Onboard to codebases by ingesting docs, ADRs, and runbooks. Ask the wiki instead of interrupting senior engineers.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"
        />
      </svg>
    ),
  },
  {
    title: "Content Creators",
    description:
      "Organize research for writing. Ingest interviews, articles, and raw notes, then query the compiled wiki for structured outlines.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10"
        />
      </svg>
    ),
  },
  {
    title: "Personal Learning",
    description:
      "Build deep understanding across topics. Feed courses, books, and articles into one wiki that connects the dots for you.",
    icon: (
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18"
        />
      </svg>
    ),
  },
];

export function UseCasesSection() {
  return (
    <section className="border-t border-zinc-900 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-4 text-center text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Who it is for
        </div>
        <h2 className="mb-12 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          Use cases
        </h2>

        <div className="grid gap-6 sm:grid-cols-2">
          {USE_CASES.map((uc) => (
            <div
              key={uc.title}
              className="group rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 transition hover:border-zinc-700"
            >
              <div className="mb-3 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-400 transition group-hover:border-brand-700 group-hover:text-brand-400">
                  {uc.icon}
                </div>
                <h3 className="font-semibold text-zinc-200">{uc.title}</h3>
              </div>
              <p className="text-sm leading-relaxed text-zinc-400">{uc.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
