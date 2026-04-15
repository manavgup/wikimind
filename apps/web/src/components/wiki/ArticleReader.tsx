import { useMemo } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { ArticleResponse, ConfidenceLevel } from "../../types/api";
import { getBaseUrl } from "../../api/client";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { PageTypeIndicator } from "./PageTypeIndicator";
import { Badge } from "../shared/Badge";

interface ArticleReaderProps {
  article: ArticleResponse;
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

export function ArticleReader({ article }: ArticleReaderProps) {
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

  return (
    <article className="mx-auto max-w-3xl p-8">
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
          {article.concepts.slice(0, 3).map((concept) => (
            <Badge key={concept} tone="brand">
              {concept}
            </Badge>
          ))}
        </div>
        <h1 className="text-3xl font-bold text-slate-900">{article.title}</h1>
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

      <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-a:text-brand-700">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
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
                  : src;
              return (
                <figure className="my-4">
                  <img
                    src={resolvedSrc}
                    alt={alt || ""}
                    className="mx-auto max-w-full rounded border border-slate-200"
                    loading="lazy"
                    {...props}
                  />
                  {alt && alt !== "Figure" && (
                    <figcaption className="mt-1 text-center text-sm text-slate-500">
                      {alt}
                    </figcaption>
                  )}
                </figure>
              );
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
