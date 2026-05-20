const FRONTMATTER_REGEX = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;
const WIKILINK_REGEX = /\[\[([^\]]+)\]\]/g;
const BROKEN_IMAGE_REGEX = /!\[[^\]]*\]\((?!\/|https?:\/\/)[^)]+\)\n*/g;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function preprocessMarkdown(content: string): string {
  return content
    .replace(FRONTMATTER_REGEX, "")
    .replace(BROKEN_IMAGE_REGEX, "")
    .replace(WIKILINK_REGEX, (_, target: string) => {
      const safe = escapeHtml(target.trim());
      return `<span class="wikilink-unresolved" title="Article not yet in wiki">${safe}</span>`;
    });
}

/** Extract synthesized_from article IDs from concept page frontmatter. */
export function extractSynthesizedFrom(content: string): string[] {
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
export function extractConceptKind(content: string): string | null {
  const match = content.match(FRONTMATTER_REGEX);
  if (!match) return null;
  const kindMatch = match[0].match(/concept_kind:\s*(.+)/);
  return kindMatch ? kindMatch[1].trim() : null;
}
