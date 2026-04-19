import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { Spinner } from "../shared/Spinner";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PdfViewerProps {
  url: string;
}

export function PdfViewer({ url }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const pdf = await pdfjsLib.getDocument(url).promise;
        if (cancelled) return;
        setPageCount(pdf.numPages);
        const container = containerRef.current;
        if (!container) return;
        container.innerHTML = "";

        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const viewport = page.getViewport({ scale: 1.5 });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.display = "block";
          canvas.style.margin = "0 auto 16px auto";
          container.appendChild(canvas);
          await page.render({ canvas, viewport }).promise;
        }
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load PDF");
          setLoading(false);
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 text-rose-600">
        {error}
      </div>
    );
  }

  return (
    <div className="relative h-full overflow-auto bg-slate-100">
      {loading && (
        <div className="flex items-center justify-center p-8">
          <Spinner size={24} />
          <span className="ml-2 text-sm text-slate-500">Loading PDF...</span>
        </div>
      )}
      <div ref={containerRef} className="p-4" />
      {!loading && pageCount > 0 && (
        <div className="sticky bottom-0 bg-white/80 px-4 py-2 text-center text-xs text-slate-500 backdrop-blur">
          {pageCount} page{pageCount !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
