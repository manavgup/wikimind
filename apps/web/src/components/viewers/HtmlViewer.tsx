import { useEffect, useState } from "react";
import { Spinner } from "../shared/Spinner";

interface HtmlViewerProps {
  url: string;
}

export function HtmlViewer({ url }: HtmlViewerProps) {
  const [html, setHtml] = useState<string | null>(null);
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
      .then(setHtml)
      .catch((err) => setError(err.message));
  }, [url]);

  if (error) {
    return <div className="p-8 text-rose-600">{error}</div>;
  }
  if (html === null) {
    return (
      <div className="flex items-center justify-center p-8">
        <Spinner size={24} />
      </div>
    );
  }

  return (
    <iframe
      srcDoc={html}
      sandbox="allow-same-origin"
      title="Source document"
      className="h-full w-full border-0"
    />
  );
}
