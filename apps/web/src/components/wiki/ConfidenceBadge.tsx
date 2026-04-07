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

interface ConfidenceBadgeProps {
  level: ConfidenceLevel;
}

export function ConfidenceBadge({ level }: ConfidenceBadgeProps) {
  return <Badge tone={TONE[level]}>{LABEL[level]}</Badge>;
}
