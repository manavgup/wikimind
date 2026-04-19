interface HtmlViewerProps {
  url: string;
}

export function HtmlViewer({ url }: HtmlViewerProps) {
  return (
    <iframe
      src={url}
      sandbox="allow-same-origin"
      title="Source document"
      className="h-full w-full border-0"
    />
  );
}
