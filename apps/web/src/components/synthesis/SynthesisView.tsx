import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createSynthesis,
  listSynthesisPages,
  listArticles,
} from "../../api/wiki";
import { Spinner } from "../shared/Spinner";
import type { Article } from "../../types/api";
import type { SynthesisResponse } from "../../api/wiki";

function SynthesisForm({
  onCreated,
}: {
  onCreated: (resp: SynthesisResponse) => void;
}) {
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showArticlePicker, setShowArticlePicker] = useState(false);

  const { data: articles } = useQuery({
    queryKey: ["articles", { page_type: "source" }],
    queryFn: () => listArticles({ page_type: "source", limit: 200 }),
  });

  const mutation = useMutation({
    mutationFn: createSynthesis,
    onSuccess: (data) => onCreated(data),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim().length < 3) return;
    mutation.mutate({
      query: query.trim(),
      article_ids: selectedIds.length > 0 ? selectedIds : undefined,
    });
  };

  const toggleArticle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div>
        <label
          htmlFor="synthesis-query"
          className="block text-sm font-medium text-slate-700"
        >
          Synthesis topic or question
        </label>
        <input
          id="synthesis-query"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "Compare transformer architectures across my papers"'
          className="mt-1 block w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
          disabled={mutation.isPending}
          data-testid="synthesis-query-input"
        />
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowArticlePicker(!showArticlePicker)}
          className="text-sm text-indigo-600 hover:text-indigo-800"
        >
          {showArticlePicker
            ? "Hide article picker"
            : `Select specific articles (${selectedIds.length} selected)`}
        </button>

        {showArticlePicker && articles && (
          <div className="mt-3 max-h-60 space-y-1 overflow-y-auto rounded-lg border border-slate-200 bg-white p-3">
            {articles.map((article) => (
              <label
                key={article.id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(article.id)}
                  onChange={() => toggleArticle(article.id)}
                  className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="truncate text-slate-700">{article.title}</span>
                <span className="ml-auto text-xs text-slate-400">
                  {article.page_type}
                </span>
              </label>
            ))}
            {articles.length === 0 && (
              <p className="py-2 text-center text-sm text-slate-400">
                No source articles found. Ingest some sources first.
              </p>
            )}
          </div>
        )}
      </div>

      {mutation.isError && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {(mutation.error as Error)?.message ||
            "Failed to create synthesis. Make sure you have at least 2 relevant articles."}
        </div>
      )}

      <button
        type="submit"
        disabled={mutation.isPending || query.trim().length < 3}
        className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        data-testid="synthesis-submit-btn"
      >
        {mutation.isPending && <Spinner size={14} />}
        {mutation.isPending ? "Synthesizing..." : "Synthesize"}
      </button>
    </form>
  );
}

function SynthesisCard({ article }: { article: Article }) {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => navigate(`/wiki/${encodeURIComponent(article.slug)}`)}
      className="block w-full rounded-lg border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300 hover:shadow-md"
    >
      <div className="flex items-start justify-between">
        <h3 className="font-medium text-slate-900">{article.title}</h3>
        <span className="ml-2 inline-flex shrink-0 items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
          synthesis
        </span>
      </div>
      {article.summary && (
        <p className="mt-1 line-clamp-2 text-sm text-slate-500">
          {article.summary}
        </p>
      )}
      <div className="mt-2 flex items-center gap-3 text-xs text-slate-400">
        <span>
          {new Date(article.created_at).toLocaleDateString()}
        </span>
        {article.source_count > 0 && (
          <span>{article.source_count} sources</span>
        )}
      </div>
    </button>
  );
}

export function SynthesisView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: syntheses, isLoading } = useQuery({
    queryKey: ["synthesis-pages"],
    queryFn: listSynthesisPages,
  });

  const handleCreated = (resp: SynthesisResponse) => {
    queryClient.invalidateQueries({ queryKey: ["synthesis-pages"] });
    queryClient.invalidateQueries({ queryKey: ["articles"] });
    navigate(`/wiki/${encodeURIComponent(resp.slug)}`);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <svg
            className="h-5 w-5 text-indigo-600"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"
            />
          </svg>
          <h1 className="text-lg font-semibold text-slate-900">Synthesis</h1>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Cross-cutting analysis across multiple sources in your wiki
        </p>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-8">
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-base font-semibold text-slate-800">
              New Synthesis
            </h2>
            <SynthesisForm onCreated={handleCreated} />
          </div>

          <div className="mt-10">
            <h2 className="mb-4 text-base font-semibold text-slate-800">
              Previous Syntheses
            </h2>
            {isLoading ? (
              <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
                <Spinner size={16} /> Loading...
              </div>
            ) : syntheses && syntheses.length > 0 ? (
              <div className="space-y-3">
                {syntheses.map((s) => (
                  <SynthesisCard key={s.id} article={s} />
                ))}
              </div>
            ) : (
              <p className="py-8 text-center text-sm text-slate-400">
                No synthesis pages yet. Create your first one above.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
