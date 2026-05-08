import { useEffect, useMemo, useState } from "react";

interface HeadingItem {
  id: string;
  text: string;
  level: number;
}

interface ArticleOutlineProps {
  content: string;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .trim();
}

const HEADING_REGEX = /^(#{2,3})\s+(.+)$/gm;

function parseHeadings(markdown: string): HeadingItem[] {
  const items: HeadingItem[] = [];
  let match: RegExpExecArray | null;
  HEADING_REGEX.lastIndex = 0;
  while ((match = HEADING_REGEX.exec(markdown)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    items.push({ id: slugify(text), text, level });
  }
  return items;
}

export function ArticleOutline({ content }: ArticleOutlineProps) {
  const headings = useMemo(() => parseHeadings(content), [content]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the first heading that is currently visible
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length > 0) {
          setActiveId(visible[0].target.id);
        }
      },
      { rootMargin: "-80px 0px -60% 0px", threshold: 0 },
    );

    for (const heading of headings) {
      const el = document.getElementById(heading.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [headings]);

  if (headings.length === 0) return null;

  return (
    <nav aria-label="Article outline" className="py-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        On this page
      </h3>
      <ul className="space-y-1">
        {headings.map((heading) => (
          <li key={heading.id}>
            <a
              href={`#${heading.id}`}
              onClick={(e) => {
                e.preventDefault();
                document
                  .getElementById(heading.id)
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
              className={`block truncate rounded px-2 py-1 text-sm transition ${
                heading.level === 3 ? "pl-5" : ""
              } ${
                activeId === heading.id
                  ? "bg-brand-50 font-medium text-brand-700"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              }`}
            >
              {heading.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
