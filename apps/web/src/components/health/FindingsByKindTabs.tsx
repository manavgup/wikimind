import { useState } from "react";
import { FindingCard } from "./FindingCard";
import type { LintReportDetail } from "../../api/lint";

interface Props {
  detail: LintReportDetail;
}

type TabKey = "contradictions" | "orphans" | "structurals";

interface TabDef {
  key: TabKey;
  label: string;
  count: number;
}

export function FindingsByKindTabs({ detail }: Props) {
  const resolvedCount = Object.keys(detail.resolutions ?? {}).length;
  const tabs: TabDef[] = [
    {
      key: "contradictions",
      label: "Contradictions",
      count: detail.contradictions.length - resolvedCount,
    },
    { key: "orphans", label: "Orphans", count: detail.orphans.length },
    {
      key: "structurals",
      label: "Structural",
      count: (detail.structurals ?? []).length,
    },
  ];

  const [activeTab, setActiveTab] = useState<TabKey>("contradictions");

  return (
    <div>
      <div className="flex border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium transition ${
              activeTab === tab.key
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}{" "}
            <span className="ml-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {activeTab === "contradictions" &&
          (detail.contradictions.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              No contradictions found.
            </p>
          ) : (
            detail.contradictions.map((f) => (
              <FindingCard key={f.id} finding={f} resolutions={detail.resolutions} />
            ))
          ))}

        {activeTab === "orphans" &&
          (detail.orphans.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              No orphan articles found.
            </p>
          ) : (
            detail.orphans.map((f) => (
              <FindingCard key={f.id} finding={f} />
            ))
          ))}

        {activeTab === "structurals" &&
          ((detail.structurals ?? []).length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">
              No structural issues found.
            </p>
          ) : (
            (detail.structurals ?? []).map((f) => (
              <FindingCard key={f.id} finding={f} />
            ))
          ))}
      </div>
    </div>
  );
}
