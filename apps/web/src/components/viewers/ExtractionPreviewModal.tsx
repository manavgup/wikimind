import { useQuery } from "@tanstack/react-query";
import { getOriginalUrl, getSourceContent } from "../../api/sources";
import type { SourceDetailResponse } from "../../types/api";
import { Badge } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { PdfViewer } from "./PdfViewer";

interface ExtractionPreviewModalProps {
  source: SourceDetailResponse;
  onClose: () => void;
}

function engineLabel(engine: string | null): string {
  switch (engine) {
    case "docling-serve":
      return "Docling";
    case "pymupdf":
      return "PyMuPDF";
    default:
      return "Unknown";
  }
}

function formatNumber(value: number | null): string {
  return value == null ? "Unknown" : value.toLocaleString();
}

export function ExtractionPreviewModal({ source, onClose }: ExtractionPreviewModalProps) {
  const contentQuery = useQuery({
    queryKey: ["source-extraction-content", source.id],
    queryFn: () => getSourceContent(source.id),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="flex h-[92vh] w-[94vw] flex-col rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-slate-900">
              {source.title || "Extraction preview"}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Badge tone="brand">Extract</Badge>
              <Badge tone={source.extraction_engine ? "info" : "neutral"}>
                Engine: {engineLabel(source.extraction_engine)}
              </Badge>
              <Badge tone="neutral">
                Pages: {formatNumber(source.extraction_page_count)}
              </Badge>
              <Badge tone="neutral">
                Tokens: {formatNumber(source.token_count)}
              </Badge>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2">
          <div className="min-h-0 overflow-hidden border-b border-slate-200 lg:border-b-0 lg:border-r">
            <PdfViewer url={getOriginalUrl(source.id)} />
          </div>

          <div className="flex min-h-0 flex-col bg-white">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <h3 className="text-sm font-semibold text-slate-900">Extracted text</h3>
              {contentQuery.data?.truncated ? (
                <Badge tone="warning">Truncated</Badge>
              ) : null}
            </div>

            {contentQuery.isLoading ? (
              <div className="flex flex-1 items-center justify-center gap-2 p-8 text-sm text-slate-500">
                <Spinner size={16} /> Loading extracted text...
              </div>
            ) : contentQuery.isError ? (
              <div className="m-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                Failed to load extracted text.
              </div>
            ) : (
              <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-4 font-mono text-sm leading-relaxed text-slate-800">
                {contentQuery.data?.content ?? ""}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
