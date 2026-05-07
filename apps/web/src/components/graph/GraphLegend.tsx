import { RELATION_COLORS, RELATION_LEGEND_ORDER } from "./relationColors";

/** Compact legend mapping edge color to relation_type. */
export function GraphLegend() {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-slate-200 bg-white/90 p-2 text-xs shadow-sm backdrop-blur">
      <div className="mb-1 font-medium text-slate-700">Relation</div>
      <ul className="space-y-1">
        {RELATION_LEGEND_ORDER.map((rel) => (
          <li key={rel} className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block h-0.5 w-5 rounded"
              style={{ backgroundColor: RELATION_COLORS[rel] }}
            />
            <span className="text-slate-600">{rel.replace("_", " ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
