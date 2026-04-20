import { useEffect, useState, useCallback, useRef } from "react";
import { getBaseUrl } from "../../api/client";

interface LoginOverlayProps {
  onClose: () => void;
}

const COMPILE_STAGES = [
  "authenticating\u2026",
  "loading your wiki\u2026",
  "indexing 214 sources\u2026",
  "almost there\u2026",
];

export function LoginOverlay({ onClose }: LoginOverlayProps) {
  const apiBase = getBaseUrl();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState(COMPILE_STAGES[0]);
  const overlayRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const runLoginFlow = useCallback(() => {
    setLoading(true);
    let i = 0;
    const tick = () => {
      if (i < COMPILE_STAGES.length) {
        setStatusText(COMPILE_STAGES[i]);
        i++;
        setTimeout(tick, 520);
      } else {
        // Redirect into the app
        window.location.href = "/inbox";
      }
    };
    tick();
  }, []);

  const handleOAuth = useCallback(
    (provider: string) => {
      if (provider === "api") {
        // API key flow — just start the animation, then redirect
        runLoginFlow();
      } else {
        // Real OAuth redirect
        window.location.href = `${apiBase}/auth/login/${provider}`;
      }
    },
    [apiBase, runLoginFlow]
  );

  const handleEmailSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (email.trim()) {
        runLoginFlow();
      }
    },
    [email, runLoginFlow]
  );

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[100] flex items-center justify-center p-6 animate-overlay-fade"
      style={{
        background: "rgba(15, 23, 42, 0.62)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
      }}
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="loginTitle"
    >
      <div
        className="grid w-full overflow-hidden rounded-2xl bg-white animate-card-rise"
        style={{
          maxWidth: "920px",
          minHeight: "560px",
          gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)",
          boxShadow: "0 24px 72px -12px rgb(15 23 42 / 0.4)",
        }}
      >
        {/* LEFT: dark welcome panel */}
        <div
          className="relative flex flex-col overflow-hidden bg-slate-900 p-10 pb-8 text-white"
          style={{ padding: "40px 40px 32px" }}
        >
          {/* Subtle radial glow */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(600px 300px at 85% 110%, rgba(70, 115, 173, 0.22), transparent 70%)",
            }}
          />

          {/* Brand */}
          <div
            className="relative z-10 flex items-center gap-2 text-[15px] font-semibold text-white"
            style={{ letterSpacing: "-0.01em" }}
          >
            <span>&#x1f9e0;</span>
            <span>WikiMind</span>
          </div>

          {/* Welcome message */}
          <div className="relative z-10 my-auto">
            <h2
              className="m-0 font-bold text-white"
              style={{
                fontSize: "32px",
                lineHeight: "1.1",
                letterSpacing: "-0.02em",
                maxWidth: "14ch",
                textWrap: "balance",
              }}
            >
              welcome back. the wiki{" "}
              <em className="font-serif-italic font-normal text-brand-300">compounded</em> while
              you were out.
            </h2>
            <p
              className="mt-5 text-[14px] text-slate-300"
              style={{ lineHeight: "1.6", maxWidth: "40ch" }}
            >
              WikiMind keeps a running record of what you&#x2019;ve read and what you&#x2019;ve
              asked. Pick up exactly where you left off — your pages, your concepts, your graph.
            </p>

            {/* Stats */}
            <div className="mt-8 flex gap-5">
              <div className="min-w-0 flex-1">
                <div
                  className="text-[22px] font-semibold text-white"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    letterSpacing: "-0.01em",
                  }}
                >
                  214
                </div>
                <div
                  className="mt-0.5 text-[10px] uppercase text-slate-400"
                  style={{ letterSpacing: "0.08em" }}
                >
                  sources
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div
                  className="text-[22px] font-semibold text-white"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    letterSpacing: "-0.01em",
                  }}
                >
                  583
                </div>
                <div
                  className="mt-0.5 text-[10px] uppercase text-slate-400"
                  style={{ letterSpacing: "0.08em" }}
                >
                  articles
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div
                  className="text-[22px] font-semibold text-white"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    letterSpacing: "-0.01em",
                  }}
                >
                  1,247
                </div>
                <div
                  className="mt-0.5 text-[10px] uppercase text-slate-400"
                  style={{ letterSpacing: "0.08em" }}
                >
                  backlinks
                </div>
              </div>
            </div>
          </div>

          {/* Version footer */}
          <div
            className="relative z-10 mt-auto pt-8 text-[11px] text-slate-500"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            v0.4.0 · local&#x2011;first · mit licensed
          </div>
        </div>

        {/* RIGHT: login form */}
        <div className="relative flex flex-col" style={{ padding: "48px 48px 40px" }}>
          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 inline-flex h-7 w-7 items-center justify-center rounded-md border-none bg-transparent text-[16px] text-slate-400 transition-all duration-100 hover:bg-slate-100 hover:text-slate-900"
            aria-label="Close"
            style={{ cursor: "pointer" }}
          >
            &#x2715;
          </button>

          {loading ? (
            /* Loading state */
            <div className="my-auto flex flex-col items-center justify-center gap-4">
              <div
                className="h-8 w-8 rounded-full border-[3px] border-slate-200 animate-spin-custom"
                style={{ borderTopColor: "#365b91" }}
              />
              <div
                className="text-[13px] text-slate-700"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {statusText}
              </div>
            </div>
          ) : (
            /* Main form */
            <div>
              <div
                className="text-[11px] font-semibold uppercase text-slate-400"
                style={{ letterSpacing: "0.08em" }}
              >
                sign in
              </div>
              <h3
                id="loginTitle"
                className="mt-2 mb-2 text-[24px] font-bold text-slate-900"
                style={{ letterSpacing: "-0.015em" }}
              >
                Open your wiki.
              </h3>
              <p className="mb-7 text-[14px] text-slate-500" style={{ lineHeight: "1.5" }}>
                Single&#x2011;click OAuth — we never see your password. Your wiki stays on disk.
              </p>

              {/* OAuth buttons */}
              <div className="flex flex-col gap-2.5">
                <button
                  type="button"
                  onClick={() => handleOAuth("github")}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-slate-300 bg-white px-3.5 py-[11px] text-[14px] font-medium text-slate-900 transition-all duration-100 hover:border-brand-400 hover:bg-slate-50"
                  style={{ fontFamily: "Inter, sans-serif", cursor: "pointer" }}
                >
                  <span className="inline-flex h-[18px] w-[18px] items-center justify-center">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="#0f172a">
                      <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 008 10.95c.58.1.79-.25.79-.56v-2c-3.25.7-3.93-1.57-3.93-1.57-.53-1.36-1.3-1.72-1.3-1.72-1.06-.72.08-.71.08-.71 1.17.08 1.78 1.2 1.78 1.2 1.04 1.78 2.73 1.27 3.4.97.1-.75.41-1.27.74-1.56-2.6-.3-5.33-1.3-5.33-5.78 0-1.28.46-2.33 1.2-3.15-.12-.3-.52-1.5.12-3.13 0 0 .98-.31 3.2 1.2a11.1 11.1 0 015.83 0c2.22-1.51 3.2-1.2 3.2-1.2.64 1.63.24 2.83.12 3.13.75.82 1.2 1.87 1.2 3.15 0 4.5-2.74 5.47-5.35 5.76.42.37.8 1.1.8 2.23v3.3c0 .32.2.68.8.56A11.5 11.5 0 0023.5 12C23.5 5.65 18.35.5 12 .5z" />
                    </svg>
                  </span>
                  Continue with GitHub
                </button>
                <button
                  type="button"
                  onClick={() => handleOAuth("google")}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-slate-300 bg-white px-3.5 py-[11px] text-[14px] font-medium text-slate-900 transition-all duration-100 hover:border-brand-400 hover:bg-slate-50"
                  style={{ fontFamily: "Inter, sans-serif", cursor: "pointer" }}
                >
                  <span className="inline-flex h-[18px] w-[18px] items-center justify-center">
                    <svg width="18" height="18" viewBox="0 0 24 24">
                      <path
                        fill="#4285F4"
                        d="M23 12.27c0-.8-.07-1.56-.2-2.3H12v4.36h6.18a5.3 5.3 0 01-2.29 3.47v2.88h3.7C21.7 18.74 23 15.8 23 12.27z"
                      />
                      <path
                        fill="#34A853"
                        d="M12 23c3.1 0 5.7-1.02 7.6-2.77l-3.71-2.88c-1.03.7-2.35 1.11-3.89 1.11-2.99 0-5.52-2.02-6.43-4.74H1.76v2.97A11 11 0 0012 23z"
                      />
                      <path
                        fill="#FBBC05"
                        d="M5.57 13.72a6.6 6.6 0 010-4.21V6.54H1.76a11 11 0 000 9.88l3.81-2.7z"
                      />
                      <path
                        fill="#EA4335"
                        d="M12 4.75c1.68 0 3.19.58 4.38 1.72l3.28-3.28C17.69 1.26 15.1 0 12 0A11 11 0 001.76 6.54l3.81 2.97C6.48 6.77 9.01 4.75 12 4.75z"
                      />
                    </svg>
                  </span>
                  Continue with Google
                </button>
                <button
                  type="button"
                  onClick={() => handleOAuth("api")}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-slate-300 bg-white px-3.5 py-[11px] text-[14px] font-medium text-slate-900 transition-all duration-100 hover:border-brand-400 hover:bg-slate-50"
                  style={{ fontFamily: "Inter, sans-serif", cursor: "pointer" }}
                >
                  <span className="inline-flex h-[18px] w-[18px] items-center justify-center">
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="#334155"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <rect x="3" y="7" width="18" height="12" rx="2" />
                      <path d="M7 11h4M7 14h7" />
                      <circle cx="17" cy="13" r="1.25" fill="#334155" stroke="none" />
                    </svg>
                  </span>
                  Use an API key
                </button>
              </div>

              {/* Divider */}
              <div
                className="my-5 flex items-center gap-3 text-[11px] font-medium uppercase text-slate-400"
                style={{ letterSpacing: "0.08em" }}
              >
                <span className="h-px flex-1 bg-slate-200" />
                or
                <span className="h-px flex-1 bg-slate-200" />
              </div>

              {/* Email magic link */}
              <form onSubmit={handleEmailSubmit} autoComplete="off">
                <div className="mb-3.5 flex flex-col gap-1.5">
                  <label htmlFor="login-email" className="text-[12px] font-medium text-slate-700">
                    Email
                  </label>
                  <input
                    type="email"
                    id="login-email"
                    placeholder="you@example.com"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="rounded-md border border-slate-300 bg-white px-3 py-[9px] text-[14px] text-slate-900 outline-none placeholder:text-slate-400 transition-all duration-100 focus:border-brand-500"
                    style={{
                      fontFamily: "Inter, sans-serif",
                      boxShadow: "none",
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.boxShadow =
                        "0 0 0 3px rgb(70 115 173 / 0.15)";
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.boxShadow = "none";
                    }}
                  />
                </div>
                <button
                  type="submit"
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-700 px-4 py-2.5 text-[14px] font-medium text-white transition-colors duration-100 hover:bg-brand-800 disabled:bg-brand-300 disabled:cursor-default"
                  style={{ fontFamily: "Inter, sans-serif", cursor: "pointer" }}
                >
                  Send magic link{" "}
                  <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>→</span>
                </button>
              </form>

              {/* Fine print */}
              <div
                className="mt-[22px] border-t border-slate-200 pt-5 text-[11px] text-slate-400"
                style={{ lineHeight: "1.55" }}
              >
                By signing in you agree to our{" "}
                <a
                  href="#"
                  className="text-slate-500 underline decoration-dotted underline-offset-2 hover:text-slate-900"
                >
                  Terms
                </a>{" "}
                and{" "}
                <a
                  href="#"
                  className="text-slate-500 underline decoration-dotted underline-offset-2 hover:text-slate-900"
                >
                  Privacy Policy
                </a>
                . Your wiki lives on your disk — we store only your account email and which LLM
                providers you&#x2019;ve connected.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
