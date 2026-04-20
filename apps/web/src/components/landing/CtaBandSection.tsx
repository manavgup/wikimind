interface CtaBandSectionProps {
  onSignIn: () => void;
}

export function CtaBandSection({ onSignIn }: CtaBandSectionProps) {
  return (
    <section className="border-t border-zinc-900 bg-gradient-to-b from-zinc-900/60 to-zinc-950 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-3xl text-center">
        <h2 className="text-2xl font-bold text-zinc-100 sm:text-3xl">
          Start building your knowledge OS
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-zinc-400">
          Feed your sources, let the compiler synthesize, and ask questions
          grounded in what you actually know.
        </p>
        <div className="mt-8">
          <button
            type="button"
            onClick={onSignIn}
            className="rounded-lg bg-brand-600 px-8 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 focus:ring-offset-zinc-950"
          >
            Sign in
          </button>
        </div>
      </div>
    </section>
  );
}
