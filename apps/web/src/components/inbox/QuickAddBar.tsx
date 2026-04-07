import { useCallback, useState, type DragEvent, type FormEvent } from "react";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";

interface QuickAddBarProps {
  onSubmitUrl: (url: string) => Promise<void> | void;
  onSubmitPdf: (file: File) => Promise<void> | void;
  isSubmittingUrl?: boolean;
  isSubmittingPdf?: boolean;
}

export function QuickAddBar({
  onSubmitUrl,
  onSubmitPdf,
  isSubmittingUrl,
  isSubmittingPdf,
}: QuickAddBarProps) {
  const [url, setUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);

  const handleUrlSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const trimmed = url.trim();
      if (!trimmed) return;
      await onSubmitUrl(trimmed);
      setUrl("");
    },
    [url, onSubmitUrl],
  );

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files) return;
      const pdfs = Array.from(files).filter(
        (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
      );
      for (const file of pdfs) {
        await onSubmitPdf(file);
      }
    },
    [onSubmitPdf],
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      void handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:flex-row md:items-stretch">
      <form onSubmit={handleUrlSubmit} className="flex flex-1 items-center gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste a URL (article, YouTube, RSS feed)..."
          className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <Button type="submit" disabled={isSubmittingUrl || url.trim() === ""}>
          {isSubmittingUrl ? <Spinner size={12} /> : null}
          Add
        </Button>
      </form>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`flex flex-1 items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-2 text-xs transition ${
          dragActive
            ? "border-brand-400 bg-brand-50 text-brand-700"
            : "border-slate-300 text-slate-500"
        }`}
      >
        {isSubmittingPdf ? <Spinner size={12} /> : <span aria-hidden>📄</span>}
        <span>Drop PDF here, or</span>
        <label className="cursor-pointer font-semibold text-brand-600 hover:underline">
          browse
          <input
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            onChange={(e) => {
              void handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>
    </div>
  );
}
