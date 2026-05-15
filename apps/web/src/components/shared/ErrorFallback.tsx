import type { FallbackProps } from "react-error-boundary";

export function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-8 text-center shadow-lg">
        <h1 className="mb-2 text-xl font-semibold text-gray-900">
          Something went wrong
        </h1>
        <p className="mb-6 text-sm text-gray-600">
          {error instanceof Error ? error.message : "An unexpected error occurred."}
        </p>
        <button
          onClick={resetErrorBoundary}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Reload
        </button>
      </div>
    </div>
  );
}
