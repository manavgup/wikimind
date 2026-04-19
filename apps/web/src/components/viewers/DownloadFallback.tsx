interface DownloadFallbackProps {
  url: string;
  filename: string;
}

export function DownloadFallback({ url, filename }: DownloadFallbackProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <p className="text-sm text-slate-500">
        This file type cannot be previewed in the browser.
      </p>
      <a
        href={url}
        download={filename}
        className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
      >
        Download original
      </a>
    </div>
  );
}
