import { useEffect, useState } from "react";
import { Spinner } from "../shared/Spinner";

interface YouTubeViewerProps {
  url: string;
  sourceUrl?: string;
}

export function YouTubeViewer({ url, sourceUrl }: YouTubeViewerProps) {
  const [transcript, setTranscript] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("wikimind_token");
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then(setTranscript)
      .catch((err) => setError(err.message));
  }, [url]);

  if (error) {
    return <div className="p-8 text-rose-600">{error}</div>;
  }
  if (transcript === null) {
    return (
      <div className="flex items-center justify-center p-8">
        <Spinner size={24} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {sourceUrl ? (
        <div className="border-b border-slate-200 bg-slate-50 px-6 py-2">
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-brand-600 hover:underline"
          >
            Watch on YouTube
          </a>
        </div>
      ) : null}
      <pre className="flex-1 overflow-auto whitespace-pre-wrap p-6 font-mono text-sm text-slate-800">
        {transcript}
      </pre>
    </div>
  );
}
