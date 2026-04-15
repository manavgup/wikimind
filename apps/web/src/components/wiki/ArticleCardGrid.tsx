import { Link } from "react-router-dom";
import { useArticles } from "../../hooks/useArticles";
import type { Article, ConfidenceLevel } from "../../types/api";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { PageTypeIndicator } from "./PageTypeIndicator";
import { Spinner } from "../shared/Spinner";

interface ArticleCardGridProps {
  activeConcept: string | null;
}

export function ArticleCardGrid({ activeConcept }: ArticleCardGridProps) {
  const articlesQuery = useArticles(
    activeConcept ? { concept: activeConcept } : {},
  );

  if (articlesQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
        <Spinner size={16} /> Loading articles...
      </div>
    );
  }

  if (articlesQuery.isError) {
    return (
      <div className="m-8 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        Failed to load articles.
      </div>
    );
  }

  const articles = articlesQuery.data ?? [];

  if (articles.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="text-lg font-semibold text-slate-800">No articles</h2>
          <p className="mt-1 text-sm text-slate-500">
            {activeConcept
              ? `No articles found for "${activeConcept}".`
              : "No articles in the wiki yet. Ingest a source to get started."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">
          {activeConcept ?? "All articles"}
          <span className="ml-2 font-normal text-slate-400">
            ({articles.length})
          </span>
        </h2>
      </div>

      <div className="grid gap-4 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
        {articles.map((article) => (
          <ArticleCard key={article.id} article={article} />
        ))}
      </div>
    </div>
  );
}

function ArticleCard({ article }: { article: Article }) {
  return (
    <Link
      to={`/wiki/${encodeURIComponent(article.slug)}`}
      className="group block rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-brand-300 hover:shadow-md"
    >
      <div className="mb-2 flex items-center gap-2">
        <PageTypeIndicator pageType={article.page_type} />
        {article.confidence ? (
          <ConfidenceBadge level={article.confidence as ConfidenceLevel} />
        ) : null}
        {typeof article.linter_score === "number" ? (
          <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700">
            {(article.linter_score * 100).toFixed(0)}%
          </span>
        ) : null}
      </div>

      <h3 className="text-sm font-semibold text-slate-900 group-hover:text-brand-700">
        {article.title}
      </h3>

      {article.summary ? (
        <p className="mt-1 line-clamp-2 text-xs text-slate-500">
          {article.summary}
        </p>
      ) : null}

      <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
        {article.source_count > 0 ? (
          <span title="Sources">
            {article.source_count} {article.source_count === 1 ? "source" : "sources"}
          </span>
        ) : null}
        {article.backlink_count > 0 ? (
          <span title="Backlinks">
            {article.backlink_count} {article.backlink_count === 1 ? "link" : "links"}
          </span>
        ) : null}
      </div>
    </Link>
  );
}
