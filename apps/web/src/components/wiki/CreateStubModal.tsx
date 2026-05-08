import { useState } from "react";

interface CreateStubModalProps {
  onClose: () => void;
  onCreate: (title: string, body: string) => Promise<void>;
}

export function CreateStubModal({ onClose, onCreate }: CreateStubModalProps) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

    setIsCreating(true);
    setError(null);
    try {
      await onCreate(title.trim(), body);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create stub page.",
      );
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/30 animate-overlay-fade"
        onClick={onClose}
      />
      <div className="animate-card-rise relative w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl">
        <h2 className="text-lg font-semibold text-slate-900">
          Create New Page
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Create a stub page for a concept not yet covered by any source.
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label
              htmlFor="stub-title"
              className="block text-sm font-medium text-slate-700"
            >
              Title
            </label>
            <input
              id="stub-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Transformer Architecture"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              autoFocus
              disabled={isCreating}
            />
          </div>

          <div>
            <label
              htmlFor="stub-body"
              className="block text-sm font-medium text-slate-700"
            >
              Body{" "}
              <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <textarea
              id="stub-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Add initial notes, links, or context..."
              rows={4}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              disabled={isCreating}
            />
          </div>

          {error ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              {error}
            </div>
          ) : null}

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isCreating}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || isCreating}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {isCreating ? "Creating..." : "Create Page"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
