import type { SourceType } from "../../types/api";
import { Button } from "../shared/Button";
import { DownloadFallback } from "./DownloadFallback";
import { HtmlViewer } from "./HtmlViewer";
import { PdfViewer } from "./PdfViewer";
import { TextViewer } from "./TextViewer";
import { YouTubeViewer } from "./YouTubeViewer";

interface DocumentViewerModalProps {
  sourceType: SourceType;
  title: string;
  url: string;
  sourceUrl?: string | null;
  onClose: () => void;
}

function viewerForType(
  sourceType: SourceType,
  url: string,
  sourceUrl?: string | null,
): React.ReactNode {
  switch (sourceType) {
    case "pdf":
      return <PdfViewer url={url} />;
    case "url":
      return <HtmlViewer url={url} sourceUrl={sourceUrl ?? undefined} />;
    case "text":
      return <TextViewer url={url} />;
    case "youtube":
      return <YouTubeViewer url={url} sourceUrl={sourceUrl ?? undefined} />;
    default:
      return <DownloadFallback url={url} filename="document" />;
  }
}

export function DocumentViewerModal({
  sourceType,
  title,
  url,
  sourceUrl,
  onClose,
}: DocumentViewerModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="flex h-[90vh] w-[90vw] flex-col rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
          <h2 className="truncate text-lg font-semibold text-slate-800">
            {title}
          </h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="flex-1 overflow-hidden">
          {viewerForType(sourceType, url, sourceUrl)}
        </div>
      </div>
    </div>
  );
}
