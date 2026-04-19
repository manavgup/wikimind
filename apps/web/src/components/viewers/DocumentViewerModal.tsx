import type { SourceType } from "../../types/api";
import { Button } from "../shared/Button";
import { DownloadFallback } from "./DownloadFallback";
import { HtmlViewer } from "./HtmlViewer";
import { PdfViewer } from "./PdfViewer";

interface DocumentViewerModalProps {
  sourceType: SourceType;
  title: string;
  url: string;
  onClose: () => void;
}

const INLINE_VIEWERS: Record<string, React.FC<{ url: string }>> = {
  pdf: PdfViewer,
  url: HtmlViewer,
};

export function DocumentViewerModal({
  sourceType,
  title,
  url,
  onClose,
}: DocumentViewerModalProps) {
  const Viewer = INLINE_VIEWERS[sourceType];

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
          {Viewer ? (
            <Viewer url={url} />
          ) : (
            <DownloadFallback url={url} filename={title} />
          )}
        </div>
      </div>
    </div>
  );
}
