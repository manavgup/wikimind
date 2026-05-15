"""Export wiki articles to PDF, LinkedIn post, or Marp slides.

PDF export converts article markdown to styled HTML suitable for
browser print-to-PDF or direct rendering. LinkedIn and slides exports
use the LLM router to rewrite content into the target format.
"""

import functools
import re

import structlog

from wikimind.engine.llm_router import LLMRouter, get_llm_router
from wikimind.models import CompletionRequest, TaskType

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# HTML template for PDF export — clean, print-friendly styling
# ---------------------------------------------------------------------------

_PDF_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    max-width: 800px;
    margin: 2rem auto;
    padding: 0 1rem;
    color: #1a1a1a;
    line-height: 1.7;
    font-size: 14px;
  }}
  h1 {{ font-size: 1.8rem; border-bottom: 2px solid #333; padding-bottom: 0.3rem; }}
  h2 {{ font-size: 1.4rem; margin-top: 1.5rem; color: #2c3e50; }}
  h3 {{ font-size: 1.15rem; margin-top: 1.2rem; color: #34495e; }}
  blockquote {{
    border-left: 4px solid #3498db;
    margin: 1rem 0;
    padding: 0.5rem 1rem;
    background: #f8f9fa;
  }}
  code {{
    background: #f0f0f0;
    padding: 0.15rem 0.3rem;
    border-radius: 3px;
    font-size: 0.9em;
  }}
  pre {{ background: #f0f0f0; padding: 1rem; border-radius: 4px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  ul, ol {{ padding-left: 1.5rem; }}
  li {{ margin-bottom: 0.3rem; }}
  a {{ color: #2980b9; }}
  @media print {{
    body {{ margin: 0; padding: 0; }}
    a {{ color: #333; text-decoration: none; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_LINKEDIN_SYSTEM_PROMPT = """\
You are a professional LinkedIn content writer. Rewrite the following wiki article \
as a compelling LinkedIn post. Follow this structure:

1. **Hook** — A bold opening line that grabs attention (question, surprising fact, \
or contrarian take).
2. **Insight** — 2-3 short paragraphs delivering the core insight from the article. \
Use simple language. Break up long sentences.
3. **CTA** — End with a question or call-to-action that invites engagement.

Rules:
- Maximum 300 words.
- Use line breaks generously for readability (LinkedIn renders single newlines).
- No markdown headers or bullet points — use plain text with line breaks.
- Do not use hashtags.
- Write in first person where appropriate.
- Output ONLY the post text, nothing else.
"""

_SLIDES_SYSTEM_PROMPT = """\
You are a presentation designer. Convert the following wiki article into a \
Marp-compatible markdown slide deck.

Rules:
- Use `---` to separate slides.
- First slide: title slide with the article title and a one-line subtitle.
- Include 4-8 content slides.
- Each slide should have a heading (## level) and 3-5 bullet points maximum.
- Keep bullet points concise (under 15 words each).
- Add a final slide titled "Key Takeaways" with 3 bullet points.
- Include a Marp front matter block at the top:
  ```
  ---
  marp: true
  theme: default
  paginate: true
  ---
  ```
- Output ONLY the Marp markdown, nothing else.
"""


def _convert_block_element(stripped: str, state: dict) -> str | None:
    """Convert a single stripped line to its HTML block element.

    Handles headings, blockquotes, lists, horizontal rules, and paragraphs.
    Mutates ``state`` to track list context (``in_list``, ``list_type``).

    Returns the HTML string, or ``None`` for empty lines.
    """
    # Close list if no longer in one
    prefix = ""
    if state["in_list"] and not stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
        close_tag = "</ol>" if state["list_type"] == "ol" else "</ul>"
        prefix = close_tag + "\n"
        state["in_list"] = False

    if not stripped:
        return prefix or None

    element = _line_to_element(stripped, state)
    return f"{prefix}{element}"


def _line_to_element(stripped: str, state: dict) -> str:
    """Map a non-empty stripped line to its HTML element.

    Mutates ``state`` to open list containers when entering a list.
    """
    # Headings
    for level, marker in enumerate(("# ", "## ", "### ", "#### "), start=1):
        if stripped.startswith(marker):
            tag = f"h{level}"
            return f"<{tag}>{_inline_format(stripped[len(marker) :])}</{tag}>"

    # Blockquotes
    if stripped.startswith("> "):
        return f"<blockquote>{_inline_format(stripped[2:])}</blockquote>"

    # Unordered list
    if stripped.startswith(("- ", "* ")):
        open_tag = ""
        if not state["in_list"]:
            open_tag = "<ul>\n"
            state["in_list"] = True
            state["list_type"] = "ul"
        return f"{open_tag}<li>{_inline_format(stripped[2:])}</li>"

    # Ordered list (simple pattern)
    if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in (".", ")"):
        open_tag = ""
        if not state["in_list"]:
            open_tag = "<ol>\n"
            state["in_list"] = True
            state["list_type"] = "ol"
        return f"{open_tag}<li>{_inline_format(stripped[2:].lstrip())}</li>"

    # Horizontal rule
    if stripped in ("---", "***", "___"):
        return "<hr>"

    # Regular paragraph
    return f"<p>{_inline_format(stripped)}</p>"


def _markdown_to_html(markdown_text: str) -> str:
    """Convert markdown to HTML using a simple line-by-line approach.

    Handles headings, bold, italic, code blocks, blockquotes, lists,
    and paragraphs. Suitable for article content rendering — not a
    full CommonMark parser, but sufficient for the structured output
    WikiMind's compiler produces.
    """
    lines = markdown_text.split("\n")
    html_parts: list[str] = []
    in_code_block = False
    state = {"in_list": False, "list_type": ""}

    for line in lines:
        stripped = line.strip()

        # Code block toggle
        if stripped.startswith("```"):
            if in_code_block:
                html_parts.append("</code></pre>")
            else:
                html_parts.append("<pre><code>")
            in_code_block = not in_code_block
            continue

        if in_code_block:
            html_parts.append(_escape_html(line))
            continue

        result = _convert_block_element(stripped, state)
        if result is not None:
            html_parts.append(result)

    if state["in_list"]:
        close_tag = "</ol>" if state["list_type"] == "ol" else "</ul>"
        html_parts.append(close_tag)
    if in_code_block:
        html_parts.append("</code></pre>")

    return "\n".join(html_parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ALLOWED_URL_SCHEMES = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)


def _sanitize_url(url: str) -> str | None:
    r"""Return the URL if it uses an allowed scheme, otherwise ``None``.

    Only ``http://``, ``https://``, and ``mailto:`` are permitted.
    Strips leading whitespace and control characters to prevent bypass
    via tab/newline injection (e.g. ``\tjavascript:``).
    """
    # Strip ASCII control characters and whitespace that could mask the scheme
    cleaned = re.sub(r"[\x00-\x20]+", "", url)
    if _ALLOWED_URL_SCHEMES.match(cleaned):
        return url
    return None


def _replace_link(match: re.Match[str]) -> str:
    """Regex replacement callback for markdown links with URL validation."""
    text, url = match.group(1), match.group(2)
    if _sanitize_url(url) is not None:
        return f'<a href="{url}">{text}</a>'
    # Unsafe scheme — render as plain text
    return text


def _inline_format(text: str) -> str:
    """Apply inline markdown formatting (bold, italic, code, links)."""
    result = _escape_html(text)
    # Inline code (must be before bold/italic to avoid conflict)
    result = re.sub(r"`([^`]+)`", r"<code>\1</code>", result)
    # Bold
    result = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", result)
    # Italic
    result = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", result)
    # Links — only allow safe URL schemes
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace_link, result)
    return result


class ExportService:
    """Convert wiki articles to PDF HTML, LinkedIn posts, and Marp slides."""

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm = llm_router or get_llm_router()

    def export_pdf_html(self, title: str, markdown_content: str) -> str:
        """Convert article markdown to styled HTML for PDF rendering.

        The returned HTML includes print-friendly CSS and can be opened
        in a browser and printed to PDF, or rendered by any HTML-to-PDF
        tool.

        Args:
            title: Article title for the HTML ``<title>`` element.
            markdown_content: Raw article markdown content.

        Returns:
            Complete HTML document as a string.
        """
        body_html = _markdown_to_html(markdown_content)
        return _PDF_HTML_TEMPLATE.format(title=_escape_html(title), body=body_html)

    async def export_linkedin(self, title: str, markdown_content: str, user_id: str) -> str:
        """Rewrite article content as a LinkedIn post via LLM.

        Args:
            title: Article title for context.
            markdown_content: Raw article markdown content.
            user_id: Optional user ID for BYOK key resolution.

        Returns:
            LinkedIn post text (plain text, under 300 words).
        """
        request = CompletionRequest(
            system=_LINKEDIN_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (f"Article title: {title}\n\nArticle content:\n{markdown_content}"),
                }
            ],
            max_tokens=1024,
            temperature=0.7,
            response_format="text",
            task_type=TaskType.EXPORT,
        )
        response = await self._llm.complete(request, user_id=user_id)
        return response.content.strip()

    async def export_slides(self, title: str, markdown_content: str, user_id: str) -> str:
        """Generate Marp-compatible slide deck from article content via LLM.

        Args:
            title: Article title for context.
            markdown_content: Raw article markdown content.
            user_id: Optional user ID for BYOK key resolution.

        Returns:
            Marp markdown slide deck.
        """
        request = CompletionRequest(
            system=_SLIDES_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (f"Article title: {title}\n\nArticle content:\n{markdown_content}"),
                }
            ],
            max_tokens=2048,
            temperature=0.4,
            response_format="text",
            task_type=TaskType.EXPORT,
        )
        response = await self._llm.complete(request, user_id=user_id)
        return response.content.strip()


@functools.lru_cache(maxsize=1)
def get_export_service() -> ExportService:
    """Return the singleton export service."""
    return ExportService()
