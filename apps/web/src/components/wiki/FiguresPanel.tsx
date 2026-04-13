import { useEffect, useState } from "react";
import { getBaseUrl } from "../../api/client";
import type { ArticleSourceRef } from "../../types/api";

interface Props {
  sources: ArticleSourceRef[];
  onImageCount?: (count: number) => void;
}

interface ImageEntry {
  url: string;
  kind: "figure" | "table";
  label: string;
}

// Probe for images by trying known filename patterns.
// TODO(#142): Replace with GET /wiki/articles/{slug}/images API.
const PATTERNS = [
  ...Array.from({ length: 15 }, (_, i) => ({
    filename: `test-picture-${i + 1}.png`,
    kind: "figure" as const,
    label: `Figure ${i + 1}`,
  })),
  ...Array.from({ length: 15 }, (_, i) => ({
    filename: `test-table-${i + 1}.png`,
    kind: "table" as const,
    label: `Table ${i + 1}`,
  })),
];

export function FiguresPanel({ sources, onImageCount }: Props) {
  const [images, setImages] = useState<ImageEntry[]>([]);
  const [selectedImg, setSelectedImg] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "figure" | "table">("all");

  const pdfSources = sources.filter((s) => s.source_type === "pdf");

  useEffect(() => {
    if (pdfSources.length === 0) return;
    const baseUrl = getBaseUrl();
    let cancelled = false;

    async function discover() {
      const found: ImageEntry[] = [];
      for (const src of pdfSources) {
        for (const p of PATTERNS) {
          const url = `${baseUrl}/images/${src.id}/${p.filename}`;
          try {
            const resp = await fetch(url, { method: "HEAD" });
            if (resp.ok && !cancelled) {
              found.push({ url, kind: p.kind, label: p.label });
            }
          } catch {
            // skip
          }
        }
      }
      if (!cancelled) {
        const sorted = found.sort((a, b) =>
          a.label.localeCompare(b.label, undefined, { numeric: true }),
        );
        setImages(sorted);
        onImageCount?.(sorted.length);
      }
    }
    discover();
    return () => {
      cancelled = true;
    };
  }, [sources]);

  if (images.length === 0) return null;

  const filtered =
    filter === "all" ? images : images.filter((i) => i.kind === filter);
  const figCount = images.filter((i) => i.kind === "figure").length;
  const tblCount = images.filter((i) => i.kind === "table").length;

  return (
    <>
      <section id="figures-tables" className="mx-auto max-w-3xl px-8 pb-12">
        <div className="border-t border-slate-200 pt-8">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-slate-900">
              Figures & Tables
            </h2>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => setFilter("all")}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  filter === "all"
                    ? "bg-slate-800 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                All ({images.length})
              </button>
              {figCount > 0 && (
                <button
                  type="button"
                  onClick={() => setFilter("figure")}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                    filter === "figure"
                      ? "bg-blue-600 text-white"
                      : "bg-blue-50 text-blue-700 hover:bg-blue-100"
                  }`}
                >
                  Figures ({figCount})
                </button>
              )}
              {tblCount > 0 && (
                <button
                  type="button"
                  onClick={() => setFilter("table")}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                    filter === "table"
                      ? "bg-amber-600 text-white"
                      : "bg-amber-50 text-amber-700 hover:bg-amber-100"
                  }`}
                >
                  Tables ({tblCount})
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {filtered.map((img) => (
              <button
                key={img.url}
                type="button"
                onClick={() => setSelectedImg(img.url)}
                className="group overflow-hidden rounded-lg border border-slate-200 bg-white transition hover:border-blue-300 hover:shadow-lg"
              >
                <div className="flex items-center justify-center bg-slate-50 p-3">
                  <img
                    src={img.url}
                    alt={img.label}
                    className="max-h-48 w-auto object-contain"
                    loading="lazy"
                  />
                </div>
                <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      img.kind === "table" ? "bg-amber-400" : "bg-blue-400"
                    }`}
                  />
                  <span className="text-sm font-medium text-slate-700">
                    {img.label}
                  </span>
                  <span className="ml-auto text-xs text-slate-400 opacity-0 transition group-hover:opacity-100">
                    Click to enlarge
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Lightbox */}
      {selectedImg && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8 backdrop-blur-sm"
          onClick={() => setSelectedImg(null)}
        >
          <div
            className="relative max-h-[90vh] max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={selectedImg}
              alt="Full size"
              className="max-h-[85vh] max-w-full rounded-lg bg-white object-contain shadow-2xl"
            />
            <button
              type="button"
              onClick={() => setSelectedImg(null)}
              className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-white text-slate-600 shadow-lg hover:bg-slate-100"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>
      )}
    </>
  );
}
