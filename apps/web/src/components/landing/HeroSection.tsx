interface HeroSectionProps {
  onSignIn: () => void;
}

export function HeroSection({ onSignIn }: HeroSectionProps) {
  return (
    <section className="relative overflow-hidden px-4 pb-24 pt-16 sm:px-6 lg:px-8">
      {/* Grid background pattern */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #71717a 1px, transparent 1px), linear-gradient(to bottom, #71717a 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />
      {/* Radial gradient overlay */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(70,115,173,0.12)_0%,_transparent_70%)]" />

      <div className="relative mx-auto max-w-5xl text-center">
        {/* Tag line */}
        <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/80 px-4 py-1.5 text-xs font-medium text-zinc-400">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-500" />
          Personal knowledge OS
        </div>

        <h1 className="text-4xl font-bold leading-tight tracking-tight text-zinc-50 sm:text-5xl lg:text-6xl">
          Your second brain,
          <br />
          <span className="bg-gradient-to-r from-brand-400 to-brand-600 bg-clip-text text-transparent">
            compiled by AI
          </span>
        </h1>

        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-zinc-400 sm:text-xl">
          Ingest any source. The LLM compiler distills it into a structured wiki.
          Ask questions answered from your knowledge, not the internet.
        </p>

        {/* CTA buttons */}
        <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <button
            type="button"
            onClick={onSignIn}
            className="rounded-lg bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 focus:ring-offset-zinc-950"
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={onSignIn}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-6 py-3 text-sm font-semibold text-zinc-300 transition hover:border-zinc-600 hover:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-600 focus:ring-offset-2 focus:ring-offset-zinc-950"
          >
            Open the wiki
          </button>
        </div>

        {/* Architecture diagram */}
        <div className="mx-auto mt-16 max-w-3xl">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 backdrop-blur sm:p-8">
            <div className="flex flex-col items-center gap-4 sm:flex-row sm:gap-0">
              {/* Sources */}
              <div className="flex-1 text-center">
                <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  Sources
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {["PDF", "URL", "YouTube", "Text"].map((src) => (
                    <span
                      key={src}
                      className="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-mono text-zinc-300"
                    >
                      {src}
                    </span>
                  ))}
                </div>
              </div>

              {/* Arrow */}
              <div className="flex items-center px-4 text-zinc-600">
                <svg
                  className="hidden h-5 w-12 sm:block"
                  viewBox="0 0 48 20"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M0 10H44M44 10L36 2M44 10L36 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <svg
                  className="block h-12 w-5 sm:hidden"
                  viewBox="0 0 20 48"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M10 0V44M10 44L2 36M10 44L18 36"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* Compiler */}
              <div className="flex-1 text-center">
                <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  LLM Compiler
                </div>
                <div className="inline-flex items-center gap-2 rounded-lg border border-brand-800/50 bg-brand-900/30 px-4 py-2 text-sm font-semibold text-brand-400">
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
                    />
                  </svg>
                  Compile
                </div>
              </div>

              {/* Arrow */}
              <div className="flex items-center px-4 text-zinc-600">
                <svg
                  className="hidden h-5 w-12 sm:block"
                  viewBox="0 0 48 20"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M0 10H44M44 10L36 2M44 10L36 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <svg
                  className="block h-12 w-5 sm:hidden"
                  viewBox="0 0 20 48"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M10 0V44M10 44L2 36M10 44L18 36"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              {/* Wiki */}
              <div className="flex-1 text-center">
                <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  Knowledge Wiki
                </div>
                <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-800/50 bg-emerald-900/30 px-4 py-2 text-sm font-semibold text-emerald-400">
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"
                    />
                  </svg>
                  Wiki
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
