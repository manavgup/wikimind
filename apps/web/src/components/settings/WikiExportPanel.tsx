import { useState } from "react";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { exportWiki } from "../../api/sharing";
import type { WikiExportFormat } from "../../api/sharing";

export function WikiExportPanel() {
  const [format, setFormat] = useState<WikiExportFormat>("obsidian");
  const [exporting, setExporting] = useState(false);

  const handleExport = () => {
    setExporting(true);
    exportWiki(format);
    // The form submission triggers a download; reset state after a delay
    setTimeout(() => setExporting(false), 2000);
  };

  return (
    <Card className="p-4">
      <p className="mb-3 text-sm text-slate-600">
        Export your entire wiki as a portable archive. Choose a format
        compatible with your preferred knowledge tool.
      </p>
      <div className="flex items-center gap-4">
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as WikiExportFormat)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 focus:border-brand-400 focus:outline-none"
          data-testid="export-format-select"
        >
          <option value="obsidian">Obsidian Vault (Markdown + Frontmatter)</option>
          <option value="markdown_json">Plain Markdown + JSON Metadata</option>
        </select>
        <Button
          onClick={handleExport}
          disabled={exporting}
          data-testid="export-wiki-btn"
        >
          {exporting ? "Exporting..." : "Export Wiki"}
        </Button>
      </div>
    </Card>
  );
}
