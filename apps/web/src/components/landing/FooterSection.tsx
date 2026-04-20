export function FooterSection() {
  return (
    <footer className="border-t border-zinc-800 px-4 py-10 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 sm:flex-row">
        <div className="flex items-center gap-2">
          <span className="text-lg">&#x1f9e0;</span>
          <span className="text-sm font-semibold text-zinc-400">WikiMind</span>
        </div>

        <div className="flex items-center gap-6 text-xs text-zinc-500">
          <a
            href="https://github.com/manavgup/wikimind"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-zinc-300"
          >
            GitHub
          </a>
          <a
            href="https://github.com/manavgup/wikimind/tree/main/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="transition hover:text-zinc-300"
          >
            Docs
          </a>
          <span className="flex items-center gap-1 text-zinc-600">
            Built with Claude
          </span>
        </div>

        <div className="text-xs text-zinc-600">
          &copy; {new Date().getFullYear()} WikiMind
        </div>
      </div>
    </footer>
  );
}
