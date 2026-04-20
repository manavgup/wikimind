export function PullQuoteSection() {
  return (
    <section className="border-t border-zinc-900 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-3xl text-center">
        <blockquote className="relative">
          <svg
            className="mx-auto mb-4 h-8 w-8 text-zinc-800"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10H14.017zM0 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151C7.546 6.068 5.983 8.789 5.983 11H10v10H0z" />
          </svg>
          <p className="text-xl leading-relaxed text-zinc-300 sm:text-2xl">
            The hottest new programming language is English.
          </p>
          <footer className="mt-6">
            <cite className="not-italic">
              <span className="text-sm font-semibold text-zinc-400">Andrej Karpathy</span>
              <span className="mx-2 text-zinc-700">&middot;</span>
              <span className="text-sm text-zinc-500">former Director of AI at Tesla</span>
            </cite>
          </footer>
        </blockquote>
      </div>
    </section>
  );
}
