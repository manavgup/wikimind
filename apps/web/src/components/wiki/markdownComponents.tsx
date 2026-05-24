import type { Components } from "react-markdown";
import { Link } from "react-router-dom";
import type { ArticleSourceRef, ConfidenceLevel } from "../../types/api";
import { getBaseUrl } from "../../api/client";
import { slugify } from "../../utils/slugify";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { InlineCitationMarker } from "./InlineCitationMarker";

const CONFIDENCE_TAG_REGEX = /\[(sourced|mixed|inferred|opinion)\]/gi;

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

function decorateConfidence(
  children: React.ReactNode,
  sources?: ArticleSourceRef[],
): React.ReactNode {
  if (typeof children === "string") {
    return splitConfidence(children, sources);
  }
  if (Array.isArray(children)) {
    return children.map((child, idx) => {
      if (typeof child === "string") {
        return <span key={idx}>{splitConfidence(child, sources)}</span>;
      }
      return child;
    });
  }
  return children;
}

function splitConfidence(
  text: string,
  sources?: ArticleSourceRef[],
): React.ReactNode[] {
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
        {sources && sources.length > 0 && (
          <InlineCitationMarker sources={sources} />
        )}
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}

/** Legacy static components (no citation markers). */
export const markdownComponents: Components = createMarkdownComponents();

/** Factory to create markdown components with optional citation markers. */
export function createMarkdownComponents(
  sources?: ArticleSourceRef[],
): Components {
  return {
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
      <table className="min-w-full divide-y divide-slate-200 text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
  th: ({ children }) => (
    <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-600">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="px-4 py-2.5 text-slate-700">{children}</td>,
  tr: ({ children }) => (
    <tr className="border-b border-slate-100 last:border-b-0">{children}</tr>
  ),
  h2: ({ children }) => {
    const text = childrenToText(children);
    return <h2 id={slugify(text)}>{children}</h2>;
  },
  h3: ({ children }) => {
    const text = childrenToText(children);
    return <h3 id={slugify(text)}>{children}</h3>;
  },
  li: ({ children }) => <li>{decorateConfidence(children, sources)}</li>,
  p: ({ children }) => <p>{decorateConfidence(children, sources)}</p>,
};
}
