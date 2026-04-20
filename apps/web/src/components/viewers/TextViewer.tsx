import { useEffect, useState } from "react";
import { Spinner } from "../shared/Spinner";

interface TextViewerProps {
  url: string;
}

export function TextViewer({ url }: TextViewerProps) {
  const [text, setText] = useState<string | null>(null);
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
      .then(setText)
      .catch((err) => setError(err.message));
  }, [url]);

  if (error) {
    return <div className="p-8 text-rose-600">{error}</div>;
  }
  if (text === null) {
    return (
      <div className="flex items-center justify-center p-8">
        <Spinner size={24} />
      </div>
    );
  }

  return (
    <pre className="h-full overflow-auto whitespace-pre-wrap p-6 font-mono text-sm text-slate-800">
      {text}
    </pre>
  );
}
