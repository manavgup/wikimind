import { useMemo } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import "katex/dist/katex.min.css";
import "highlight.js/styles/github.css";
import type { ArticleResponse, ConfidenceLevel } from "../../types/api";
import { Breadcrumbs } from "./Breadcrumbs";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { PageTypeIndicator } from "./PageTypeIndicator";
import { Badge } from "../shared/Badge";
import { ExportDropdown } from "./ExportDropdown";
import { ShareButton } from "./ShareButton";
import { TagSelector } from "./TagSelector";
import { preprocessMarkdown, extractSynthesizedFrom, extractConceptKind } from "./preprocessMarkdown";
import { markdownComponents } from "./markdownComponents";
import { useArticleEditor } from "./useArticleEditor";
import { ClaimsPanel } from "./ClaimsPanel";
import { DiscussionPanel } from "./DiscussionPanel";

interface ArticleReaderProps {
  article: ArticleResponse;
  onArticleUpdated?: (article: ArticleResponse) => void;
}

export function ArticleReader({ article, onArticleUpdated }: ArticleReaderProps) {
  const {
    isEditing,
    editContent,
    setEditContent,
    isSaving,
    saveError,
    handleEdit,
    handleCancel,
    handleSave,
  } = useArticleEditor({ article, onArticleUpdated });

  const processed = useMemo(
    () => preprocessMarkdown(article.content ?? ""),
    [article.content],
  );

  const isConcept = article.page_type === "concept";
  const synthesizedFrom = useMemo(
    () => (isConcept ? extractSynthesizedFrom(article.content ?? "") : []),
    [article.content, isConcept],
  );
  const conceptKind = useMemo(
    () => (isConcept ? extractConceptKind(article.content ?? "") : null),
    [article.content, isConcept],
  );

  const primaryConcept = article.concepts.length > 0 ? article.concepts[0] : null;

  return (
    <article className="mx-auto max-w-3xl p-8">
      <Breadcrumbs concept={primaryConcept} articleTitle={article.title} />
      <header className="mb-6 border-b border-slate-200 pb-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <PageTypeIndicator pageType={article.page_type} />
          {article.confidence ? (
            <ConfidenceBadge level={article.confidence as ConfidenceLevel} />
          ) : null}
          {typeof article.linter_score === "number" ? (
            <Badge tone="info">
              Linter {(article.linter_score * 100).toFixed(0)}%
            </Badge>
          ) : null}
          {isConcept && conceptKind ? (
            <Badge tone="neutral">{conceptKind}</Badge>
          ) : null}
          {article.is_stub ? (
            <Badge tone="warning">Stub</Badge>
          ) : null}
          {article.manually_edited ? (
            <Badge tone="neutral">Edited</Badge>
          ) : null}
          {article.concepts.slice(0, 3).map((concept) => (
            <Badge key={concept} tone="brand">
              {concept}
            </Badge>
          ))}
        </div>
        <div className="mt-2">
          <TagSelector
            articleId={article.id}
            currentTags={article.tags ?? []}
            onTagsChanged={onArticleUpdated ? () => onArticleUpdated(article) : undefined}
          />
        </div>
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            {article.title}
          </h1>
          <div className="flex items-center gap-2">
            <ExportDropdown slug={article.slug} articleContent={article.content} />
            <ShareButton articleId={article.id} />
            {!isEditing ? (
              <button
                onClick={handleEdit}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Edit
              </button>
            ) : null}
          </div>
        </div>
        {article.summary ? (
          <p className="mt-2 text-base text-slate-600">{article.summary}</p>
        ) : null}

        {isConcept && synthesizedFrom.length > 0 ? (
          <div className="mt-3 rounded-md border border-brand-100 bg-brand-50 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-700">
              Synthesized from
            </p>
            <ul className="flex flex-wrap gap-2">
              {synthesizedFrom.map((sourceId) => (
                <li key={sourceId}>
                  <Link
                    to={`/wiki/${encodeURIComponent(sourceId)}`}
                    className="inline-block rounded-md border border-brand-200 bg-white px-2 py-0.5 text-xs text-brand-700 hover:bg-brand-50"
                  >
                    {sourceId}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </header>

      {isEditing ? (
        <div className="space-y-4">
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="w-full min-h-[400px] rounded-md border border-slate-300 bg-white p-4 font-mono text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            disabled={isSaving}
          />
          {saveError ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              {saveError}
            </div>
          ) : null}
          <div className="flex gap-3">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={handleCancel}
              disabled={isSaving}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-a:text-brand-700">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex, rehypeHighlight, rehypeRaw]}
            components={markdownComponents}
          >
            {processed}
          </ReactMarkdown>
        </div>
      )}

      {/* Per-claim confidence panel */}
      {!isEditing && (
        <div className="mt-8 border-t border-slate-200 pt-6">
          <ClaimsPanel articleId={article.id} />
        </div>
      )}

      {/* Discussion panel for HITL compilation guidance */}
      {!isEditing && (
        <div className="mt-8 border-t border-slate-200 pt-6">
          <DiscussionPanel articleId={article.id} />
        </div>
      )}
    </article>
  );
}
