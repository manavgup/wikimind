import { useEffect, useState } from "react";
import { getBaseUrl } from "../../api/client";

interface LoginOverlayProps {
  onClose: () => void;
}

export function LoginOverlay({ onClose }: LoginOverlayProps) {
  const apiBase = getBaseUrl();
  const [email, setEmail] = useState("");
  const [magicLinkSent, setMagicLinkSent] = useState(false);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleMagicLink = (e: React.FormEvent) => {
    e.preventDefault();
    if (email.trim()) {
      setMagicLinkSent(true);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative flex w-full max-w-3xl overflow-hidden rounded-2xl shadow-2xl animate-scale-in mx-4">
        {/* Left pane - Welcome */}
        <div className="hidden w-[45%] flex-col justify-between bg-zinc-900 p-8 md:flex">
          <div>
            <div className="flex items-center gap-2 mb-8">
              <span className="text-2xl">&#x1f9e0;</span>
              <span className="text-lg font-bold text-zinc-100">WikiMind</span>
            </div>
            <h2 className="text-xl font-semibold text-zinc-100 mb-3">
              Welcome back
            </h2>
            <p className="text-sm text-zinc-400 mb-8">
              Sign in to access your personal knowledge wiki.
            </p>

            <ul className="space-y-4">
              {[
                { text: "Ingest any source with one click", icon: UploadIcon },
                { text: "AI-compiled structured wiki", icon: CompileIcon },
                { text: "Ask questions, get grounded answers", icon: ChatIcon },
              ].map((item) => (
                <li key={item.text} className="flex items-start gap-3">
                  <span className="mt-0.5 shrink-0 text-brand-400">
                    <item.icon />
                  </span>
                  <span className="text-sm text-zinc-300">{item.text}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Animated dots decoration */}
          <div className="mt-8">
            <NetworkDecoration />
          </div>
        </div>

        {/* Right pane - Auth form */}
        <div className="flex flex-1 flex-col bg-zinc-50 p-8 sm:p-10">
          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 rounded-lg p-1 text-zinc-400 transition hover:bg-zinc-200 hover:text-zinc-700"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>

          <div className="flex flex-1 flex-col justify-center">
            <h2 className="text-xl font-bold text-zinc-900 mb-2">
              Sign in to WikiMind
            </h2>
            <p className="text-sm text-zinc-500 mb-8">
              Choose your preferred sign-in method
            </p>

            {/* OAuth buttons */}
            <div className="space-y-3 mb-6">
              <a
                href={`${apiBase}/auth/login/google`}
                className="flex w-full items-center justify-center gap-3 rounded-lg border border-zinc-300 bg-white px-4 py-2.5 text-sm font-medium text-zinc-900 shadow-sm transition hover:bg-zinc-50 hover:shadow no-underline"
              >
                <GoogleIcon />
                Continue with Google
              </a>
              <a
                href={`${apiBase}/auth/login/github`}
                className="flex w-full items-center justify-center gap-3 rounded-lg border border-zinc-300 bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-zinc-800 no-underline"
              >
                <GitHubIcon />
                Continue with GitHub
              </a>
            </div>

            {/* Divider */}
            <div className="relative mb-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-zinc-200" />
              </div>
              <div className="relative flex justify-center">
                <span className="bg-zinc-50 px-3 text-xs text-zinc-400">or</span>
              </div>
            </div>

            {/* Magic link */}
            {magicLinkSent ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-center">
                <p className="text-sm font-medium text-emerald-800">
                  Check your email
                </p>
                <p className="mt-1 text-xs text-emerald-600">
                  We sent a sign-in link to {email}
                </p>
              </div>
            ) : (
              <form onSubmit={handleMagicLink} className="space-y-3">
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                />
                <button
                  type="submit"
                  className="w-full rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
                >
                  Send magic link
                </button>
              </form>
            )}
          </div>

          <p className="mt-6 text-center text-xs text-zinc-400">
            By signing in, you agree to our Terms of Service and Privacy Policy
          </p>
        </div>
      </div>
    </div>
  );
}

// --- Small icons ---

function GoogleIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
      />
    </svg>
  );
}

function CompileIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8 1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
      />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"
      />
    </svg>
  );
}

function NetworkDecoration() {
  return (
    <div className="relative h-20 w-full overflow-hidden opacity-30">
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 200 80">
        {/* Animated network nodes */}
        <circle cx="30" cy="40" r="3" fill="#4673ad" className="animate-pulse" />
        <circle cx="70" cy="20" r="2.5" fill="#4673ad" className="animate-pulse" style={{ animationDelay: "0.5s" }} />
        <circle cx="110" cy="50" r="3" fill="#4673ad" className="animate-pulse" style={{ animationDelay: "1s" }} />
        <circle cx="150" cy="30" r="2" fill="#4673ad" className="animate-pulse" style={{ animationDelay: "1.5s" }} />
        <circle cx="180" cy="60" r="2.5" fill="#4673ad" className="animate-pulse" style={{ animationDelay: "0.3s" }} />

        {/* Connecting lines */}
        <line x1="30" y1="40" x2="70" y2="20" stroke="#4673ad" strokeWidth="0.5" opacity="0.5" />
        <line x1="70" y1="20" x2="110" y2="50" stroke="#4673ad" strokeWidth="0.5" opacity="0.5" />
        <line x1="110" y1="50" x2="150" y2="30" stroke="#4673ad" strokeWidth="0.5" opacity="0.5" />
        <line x1="150" y1="30" x2="180" y2="60" stroke="#4673ad" strokeWidth="0.5" opacity="0.5" />
        <line x1="30" y1="40" x2="110" y2="50" stroke="#4673ad" strokeWidth="0.5" opacity="0.3" />
      </svg>
    </div>
  );
}
