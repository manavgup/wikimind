import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createSynthesis,
  listSynthesisPages,
  listArticles,
  getSynthesisSuggestions,
} from "../../api/wiki";
import { Spinner } from "../shared/Spinner";
import { SynthesisWizard } from "./SynthesisWizard";
import type { Article } from "../../types/api";
import type { SynthesisResponse, SynthesisSuggestion } from "../../api/wiki";

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

function SuggestionCard({
  suggestion,
  onCreateSynthesis,
  isCreating,
}: {
  suggestion: SynthesisSuggestion;
  onCreateSynthesis: (suggestion: SynthesisSuggestion) => void;
  isCreating: boolean;
}) {
  const typeLabels: Record<string, string> = {
    shared_concepts: "Shared Concepts",
    contradiction: "Contradictions",
    same_topic_different_sources: "Different Perspectives",
  };

  const typeColors: Record<string, string> = {
    shared_concepts: "bg-blue-50 text-blue-700",
    contradiction: "bg-amber-50 text-amber-700",
    same_topic_different_sources: "bg-emerald-50 text-emerald-700",
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${typeColors[suggestion.suggested_type] || "bg-slate-50 text-slate-700"}`}
          >
            {typeLabels[suggestion.suggested_type] || suggestion.suggested_type}
          </span>
          <p className="mt-2 text-sm text-slate-600">{suggestion.reason}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {suggestion.article_titles.map((title, idx) => (
              <span
                key={idx}
                className="inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
              >
                {title}
              </span>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={() => onCreateSynthesis(suggestion)}
          disabled={isCreating}
          className="ml-3 shrink-0 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
          data-testid="suggestion-create-btn"
        >
          {isCreating ? "Creating..." : "Create"}
        </button>
      </div>
    </div>
  );
}

export function SynthesisView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: syntheses, isLoading } = useQuery({
    queryKey: ["synthesis-pages"],
    queryFn: listSynthesisPages,
  });

  const { data: suggestions, isLoading: suggestionsLoading } = useQuery({
    queryKey: ["synthesis-suggestions"],
    queryFn: getSynthesisSuggestions,
  });

  const suggestionMutation = useMutation({
    mutationFn: createSynthesis,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["synthesis-pages"] });
      queryClient.invalidateQueries({ queryKey: ["synthesis-suggestions"] });
      queryClient.invalidateQueries({ queryKey: ["articles"] });
      navigate(`/wiki/${encodeURIComponent(data.slug)}`);
    },
  });

  const handleCreateFromSuggestion = (suggestion: SynthesisSuggestion) => {
    suggestionMutation.mutate({
      query: suggestion.reason,
      article_ids: suggestion.article_ids,
    });
  };

  const handleCreated = (resp: SynthesisResponse) => {
    queryClient.invalidateQueries({ queryKey: ["synthesis-pages"] });
    queryClient.invalidateQueries({ queryKey: ["synthesis-suggestions"] });
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
            <SynthesisWizard onCreated={handleCreated} />
          </div>

          {/* Suggested Syntheses */}
          {suggestionsLoading ? (
            <div className="mt-8 flex items-center gap-2 text-sm text-slate-500">
              <Spinner size={16} /> Loading suggestions...
            </div>
          ) : suggestions && suggestions.length > 0 ? (
            <div className="mt-8">
              <h2 className="mb-4 text-base font-semibold text-slate-800">
                Suggested Syntheses
              </h2>
              <div className="space-y-3">
                {suggestions.map((s, idx) => (
                  <SuggestionCard
                    key={idx}
                    suggestion={s}
                    onCreateSynthesis={handleCreateFromSuggestion}
                    isCreating={suggestionMutation.isPending}
                  />
                ))}
              </div>
            </div>
          ) : null}

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
