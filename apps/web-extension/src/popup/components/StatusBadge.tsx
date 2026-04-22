import type { IngestStatus } from "../../types";

const STATUS_COLORS: Record<IngestStatus, string> = {
  pending: "#f59e0b",
  processing: "#3b82f6",
  compiled: "#22c55e",
  failed: "#ef4444",
};

const STATUS_LABELS: Record<IngestStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  compiled: "Compiled",
  failed: "Failed",
};

interface Props {
  status: IngestStatus;
}

export function StatusBadge({ status }: Props) {
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: "11px",
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: "9999px",
        backgroundColor: `${STATUS_COLORS[status]}20`,
        color: STATUS_COLORS[status],
      }}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
