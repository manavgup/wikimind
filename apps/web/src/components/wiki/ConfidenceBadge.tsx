import type { ConfidenceLevel } from "../../types/api";
import { Badge, type BadgeTone } from "../shared/Badge";

const TONE: Record<ConfidenceLevel, BadgeTone> = {
  sourced: "success",
  mixed: "info",
  inferred: "warning",
  opinion: "neutral",
};

const LABEL: Record<ConfidenceLevel, string> = {
  sourced: "Sourced",
  mixed: "Mixed",
  inferred: "Inferred",
  opinion: "Opinion",
};

function scoreColor(score: number): string {
  if (score >= 0.8) return "text-emerald-700";
  if (score >= 0.5) return "text-amber-700";
  return "text-rose-700";
}

interface ConfidenceBadgeProps {
  level: ConfidenceLevel;
  /** Numeric confidence score (0-1). When provided, displayed as a percentage. */
  score?: number;
}

export function ConfidenceBadge({ level, score }: ConfidenceBadgeProps) {
  const label = LABEL[level];
  const pct = score !== undefined ? Math.round(score * 100) : null;

  return (
    <Badge tone={TONE[level]}>
      {label}
      {pct !== null && (
        <>
          <span className="mx-0.5 text-slate-400">&middot;</span>
          <span className={scoreColor(score!)}>{pct}%</span>
        </>
      )}
    </Badge>
  );
}
