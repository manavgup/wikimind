import type { RelationType } from "../../types/api";

/** Edge colors by typed relation. Keep in sync with backend RelationType enum. */
export const RELATION_COLORS: Record<RelationType, string> = {
  contradicts: "#dc2626",
  supersedes: "#9333ea",
  extends: "#16a34a",
  synthesizes: "#2563eb",
  references: "#6b7280",
  related_to: "#d1d5db",
};

export const DEFAULT_RELATION_COLOR = RELATION_COLORS.references;

/** Display order in the legend. */
export const RELATION_LEGEND_ORDER: RelationType[] = [
  "contradicts",
  "supersedes",
  "extends",
  "synthesizes",
  "references",
  "related_to",
];
