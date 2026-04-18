import { getBaseUrl } from "../../api/client";

export default function LoginPage() {
  const apiBase = getBaseUrl();

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <div className="w-full max-w-sm space-y-6 rounded-xl border border-zinc-800 bg-zinc-900 p-8">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-zinc-100">WikiMind</h1>
          <p className="mt-1 text-sm text-zinc-400">Sign in to your knowledge wiki</p>
        </div>

        <div className="space-y-3">
          <a
            href={`${apiBase}/auth/login/google`}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 font-medium text-zinc-900 transition-colors hover:bg-zinc-100"
          >
            Sign in with Google
          </a>
          <a
            href={`${apiBase}/auth/login/github`}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2.5 font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
          >
            Sign in with GitHub
          </a>
        </div>
      </div>
    </div>
  );
}
