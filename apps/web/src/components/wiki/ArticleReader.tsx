import { useCallback, useMemo, useState } from "react";
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
import { getBaseUrl } from "../../api/client";
import { slugify } from "../../utils/slugify";
import { Breadcrumbs } from "./Breadcrumbs";
import { editArticle } from "../../api/wiki";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { PageTypeIndicator } from "./PageTypeIndicator";
import { Badge } from "../shared/Badge";
import { ExportDropdown } from "./ExportDropdown";
import { ShareButton } from "./ShareButton";
import { TagSelector } from "./TagSelector";

interface ArticleReaderProps {
  article: ArticleResponse;
  onArticleUpdated?: (article: ArticleResponse) => void;
}

const CONFIDENCE_TAG_REGEX = /\[(sourced|mixed|inferred|opinion)\]/gi;
const WIKILINK_REGEX = /\[\[([^\]]+)\]\]/g;
const FRONTMATTER_REGEX = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const BROKEN_IMAGE_REGEX = /!\[[^\]]*\]\((?!\/|https?:\/\/)[^)]+\)\n*/g;

function childrenToText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  if (
    children &&
    typeof children === "object" &&
    "props" in children &&
    children.props?.children
  ) {
    return childrenToText(children.props.children);
  }
  return "";
}

function preprocessMarkdown(content: string): string {
  return content
    .replace(FRONTMATTER_REGEX, "")
    .replace(BROKEN_IMAGE_REGEX, "")
    .replace(WIKILINK_REGEX, (_, target: string) => {
      const safe = escapeHtml(target.trim());
      return `<span class="wikilink-unresolved" title="Article not yet in wiki">${safe}</span>`;
    });
}

/** Extract synthesized_from article IDs from concept page frontmatter. */
function extractSynthesizedFrom(content: string): string[] {
  const match = content.match(FRONTMATTER_REGEX);
  if (!match) return [];
  const fm = match[0];
  const synMatch = fm.match(/synthesized_from:\s*\n((?:\s*-\s*.+\n)*)/);
  if (!synMatch) return [];
  return synMatch[1]
    .split("\n")
    .map((line) => line.replace(/^\s*-\s*/, "").trim())
    .filter(Boolean);
}

/** Extract concept_kind from concept page frontmatter. */
function extractConceptKind(content: string): string | null {
  const match = content.match(FRONTMATTER_REGEX);
  if (!match) return null;
  const kindMatch = match[0].match(/concept_kind:\s*(.+)/);
  return kindMatch ? kindMatch[1].trim() : null;
}

export function ArticleReader({ article, onArticleUpdated }: ArticleReaderProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  const handleEdit = useCallback(() => {
    setEditContent(article.content ?? "");
    setSaveError(null);
    setIsEditing(true);
  }, [article.content]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setSaveError(null);
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      const updated = await editArticle(article.slug, { content: editContent });
      setIsEditing(false);
      onArticleUpdated?.(updated);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save changes.",
      );
    } finally {
      setIsSaving(false);
    }
  }, [article.slug, editContent, onArticleUpdated]);

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
            components={{
              a: ({ node: _node, href, children }) => {
                if (href && href.startsWith("/wiki/")) {
                  return (
                    <Link
                      to={href}
                      className="text-brand-700 underline decoration-dotted underline-offset-2 hover:text-brand-900"
                    >
                      {children}
                    </Link>
                  );
                }
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-brand-700 underline"
                  >
                    {children}
                  </a>
                );
              },
              img: ({ node: _node, src, alt, ...props }) => {
                const resolvedSrc =
                  src && src.startsWith("/images/")
                    ? `${getBaseUrl()}${src}`
                    : src && src.startsWith("/api/")
                      ? `${getBaseUrl()}${src}`
                      : src;
                return (
                  <figure className="my-6">
                    <img
                      src={resolvedSrc}
                      alt={alt || ""}
                      className="mx-auto max-w-full rounded-lg border border-slate-200 shadow-sm"
                      loading="lazy"
                      {...props}
                    />
                    {alt && alt !== "Figure" && (
                      <figcaption className="mt-2 text-center text-sm italic text-slate-500">
                        {alt}
                      </figcaption>
                    )}
                  </figure>
                );
              },
              pre: ({ children }) => (
                <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed">
                  {children}
                </pre>
              ),
              code: ({ node: _node, className, children, ...props }) => {
                const isInline = !className;
                if (isInline) {
                  return (
                    <code
                      className="rounded bg-slate-100 px-1.5 py-0.5 text-sm font-medium text-slate-800"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                }
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              },
              table: ({ children }) => (
                <div className="my-6 overflow-x-auto rounded-lg border border-slate-200">
                  <table className="min-w-full divide-y divide-slate-200 text-sm">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-slate-50">
                  {children}
                </thead>
              ),
              th: ({ children }) => (
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-600">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="px-4 py-2.5 text-slate-700">
                  {children}
                </td>
              ),
              tr: ({ children }) => (
                <tr className="border-b border-slate-100 last:border-b-0">
                  {children}
                </tr>
              ),
              h2: ({ children }) => {
                const text = childrenToText(children);
                return <h2 id={slugify(text)}>{children}</h2>;
              },
              h3: ({ children }) => {
                const text = childrenToText(children);
                return <h3 id={slugify(text)}>{children}</h3>;
              },
              li: ({ children }) => (
                <li>{decorateConfidence(children)}</li>
              ),
              p: ({ children }) => <p>{decorateConfidence(children)}</p>,
            }}
          >
            {processed}
          </ReactMarkdown>
        </div>
      )}
    </article>
  );
}

function decorateConfidence(children: React.ReactNode): React.ReactNode {
  if (typeof children === "string") {
    return splitConfidence(children);
  }
  if (Array.isArray(children)) {
    return children.map((child, idx) => {
      if (typeof child === "string") {
        return <span key={idx}>{splitConfidence(child)}</span>;
      }
      return child;
    });
  }
  return children;
}

function splitConfidence(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  CONFIDENCE_TAG_REGEX.lastIndex = 0;
  while ((match = CONFIDENCE_TAG_REGEX.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const level = match[1].toLowerCase() as ConfidenceLevel;
    parts.push(
      <span key={`${match.index}-${level}`} className="ml-1 align-middle">
        <ConfidenceBadge level={level} />
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}
