import { getBaseUrl } from "../../api/client";

export default function LoginPage() {
  const apiBase = getBaseUrl();

  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <div className="w-full max-w-sm space-y-6 rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-slate-900">WikiMind</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to your knowledge wiki</p>
        </div>

        <div className="space-y-3">
          <a
            href={`${apiBase}/auth/login/google`}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 font-medium text-white transition-colors hover:bg-brand-700"
          >
            Sign in with Google
          </a>
          <a
            href={`${apiBase}/auth/login/github`}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 font-medium text-slate-900 transition-colors hover:bg-slate-50"
          >
            Sign in with GitHub
          </a>
        </div>
      </div>
    </div>
  );
}
