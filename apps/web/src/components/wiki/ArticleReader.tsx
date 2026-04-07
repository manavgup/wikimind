import { useMemo } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { ArticleResponse, ConfidenceLevel } from "../../types/api";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Badge } from "../shared/Badge";

interface ArticleReaderProps {
  article: ArticleResponse;
}

const CONFIDENCE_TAG_REGEX = /\[(sourced|mixed|inferred|opinion)\]/gi;
const WIKILINK_REGEX = /\[\[([^\]]+)\]\]/g;

function slugify(title: string): string {
  return title
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
}

// Pre-process the markdown to convert [[wikilinks]] into a token react-markdown
// passes through. We use a HTML <a> tag with a data-wikilink attribute so the
// custom anchor renderer below can intercept it and emit a React Router <Link>.
function preprocessMarkdown(content: string): string {
  return content.replace(WIKILINK_REGEX, (_, target: string) => {
    const safe = target.trim();
    return `<a data-wikilink="${slugify(safe)}" href="#">${safe}</a>`;
  });
}

export function ArticleReader({ article }: ArticleReaderProps) {
  const processed = useMemo(
    () => preprocessMarkdown(article.content ?? ""),
    [article.content],
  );

  return (
    <article className="mx-auto max-w-3xl p-8">
      <header className="mb-6 border-b border-slate-200 pb-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {article.confidence ? (
            <ConfidenceBadge level={article.confidence as ConfidenceLevel} />
          ) : null}
          {typeof article.linter_score === "number" ? (
            <Badge tone="info">
              Linter {(article.linter_score * 100).toFixed(0)}%
            </Badge>
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
      </header>

      <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-a:text-brand-700">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={{
            a: ({ node: _node, href, children, ...props }) => {
              const wikilink = (props as { "data-wikilink"?: string })[
                "data-wikilink"
              ];
              if (wikilink) {
                return (
                  <Link
                    to={`/wiki/${encodeURIComponent(wikilink)}`}
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

// Walk text children and replace [sourced]/[inferred]/[opinion]/[mixed]
// markers with inline confidence badges. Non-string children are passed through.
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
