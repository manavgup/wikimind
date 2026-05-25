import type { SourceSpanResponse } from "../../types/api";

/** Format a human-readable locator string for a source span. */
export function formatLocator(span: SourceSpanResponse): string {
  switch (span.locator_kind) {
    case "pdf-page-rect": {
      const page = span.locator.page ?? span.locator.page_number;
      return page != null ? `page ${page}` : "";
    }
    case "html-xpath-offset": {
      const para = span.locator.paragraph ?? span.locator.index;
      return para != null ? `paragraph #${para}` : "";
    }
    case "text-byte-range":
      return "text";
    case "youtube-timestamp": {
      const ts = span.locator.timestamp ?? span.locator.start;
      return ts != null ? `${ts}s` : "";
    }
    default:
      return "";
  }
}
