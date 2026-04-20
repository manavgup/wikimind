interface CtaBandSectionProps {
  onSignIn: () => void;
}

export function CtaBandSection({ onSignIn }: CtaBandSectionProps) {
  return (
    <section className="border-b border-slate-200 bg-slate-50 py-20" id="cta">
      <div className="mx-auto max-w-[1120px] px-8">
        <div
          className="grid items-center gap-8 rounded-2xl border border-slate-200 bg-white p-12"
          style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}
        >
          <div>
            <h2
              className="m-0 font-bold text-slate-900"
              style={{
                fontSize: "32px",
                lineHeight: "1.1",
                letterSpacing: "-0.02em",
                maxWidth: "18ch",
              }}
            >
              Start feeding the wiki.
            </h2>
            <p className="mt-2 text-[15px] text-slate-500">
              Sign in with your email or an LLM provider. The first compile runs in under a minute.
            </p>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onSignIn}
              className="inline-flex items-center gap-1.5 rounded-md border border-transparent bg-brand-700 px-[18px] py-2.5 text-[14px] font-medium text-white transition-colors duration-100 hover:bg-brand-800"
            >
              Open WikiMind <span>→</span>
            </button>
            <a
              href="https://github.com/manavgup/wikimind"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center rounded-md border border-slate-300 bg-white px-[18px] py-2.5 text-[14px] font-medium text-slate-700 transition-colors duration-100 hover:border-brand-300 hover:text-slate-900"
            >
              View on GitHub
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
