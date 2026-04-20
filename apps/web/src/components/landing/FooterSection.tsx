interface FooterSectionProps {
  onSignIn: () => void;
}

export function FooterSection({ onSignIn }: FooterSectionProps) {
  return (
    <footer className="bg-slate-900 pb-12 pt-14 text-[13px] text-slate-400">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="grid items-start gap-8" style={{ gridTemplateColumns: "2fr 1fr 1fr 1fr" }}>
          {/* Brand */}
          <div>
            <div
              className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-white"
              style={{ letterSpacing: "-0.01em" }}
            >
              <span>&#x1f9e0;</span> WikiMind
            </div>
            <p className="m-0 text-[13px] text-slate-500" style={{ lineHeight: "1.55", maxWidth: "38ch" }}>
              A personal knowledge OS. Feed it sources, ask it anything, file good answers back.
              The LLM maintains the wiki; you do the thinking.
            </p>
          </div>

          {/* Product */}
          <div>
            <h4
              className="mb-3 text-[11px] font-semibold uppercase text-slate-300"
              style={{ letterSpacing: "0.08em" }}
            >
              Product
            </h4>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              <li>
                <a
                  href="#how"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById("how")?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  How it works
                </a>
              </li>
              <li>
                <a
                  href="#architecture"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById("architecture")?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  Architecture
                </a>
              </li>
              <li>
                <a
                  href="#cases"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById("cases")?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  Use cases
                </a>
              </li>
              <li>
                <button
                  type="button"
                  onClick={onSignIn}
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  Sign in
                </button>
              </li>
            </ul>
          </div>

          {/* Resources */}
          <div>
            <h4
              className="mb-3 text-[11px] font-semibold uppercase text-slate-300"
              style={{ letterSpacing: "0.08em" }}
            >
              Resources
            </h4>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              <li>
                <a
                  href="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  The original gist
                </a>
              </li>
              <li>
                <a
                  href="https://github.com/manavgup/wikimind"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  GitHub
                </a>
              </li>
              <li>
                <a
                  href="#faq"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById("faq")?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  FAQ
                </a>
              </li>
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4
              className="mb-3 text-[11px] font-semibold uppercase text-slate-300"
              style={{ letterSpacing: "0.08em" }}
            >
              Legal
            </h4>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              <li>
                <a
                  href="#"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  Privacy
                </a>
              </li>
              <li>
                <a
                  href="#"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  Terms
                </a>
              </li>
              <li>
                <a
                  href="#"
                  className="text-[13px] text-slate-400 transition-colors duration-100 hover:text-white"
                >
                  Security
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Colophon */}
        <div
          className="mt-12 flex items-center justify-between border-t pt-6 text-[12px] text-slate-500"
          style={{ borderTopColor: "rgba(255,255,255,0.08)" }}
        >
          <span>© 2026 WikiMind · local&#x2011;first, open source</span>
          <span>
            <code
              className="text-[11px] text-slate-400"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              v0.4.0 · commit 7a3f1e9
            </code>
          </span>
        </div>
      </div>
    </footer>
  );
}
