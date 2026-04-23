import type { ClipState } from "./ClipTab";

interface Props {
  state: ClipState;
  onClick: () => void;
  disabled: boolean;
}

const LABELS: Record<ClipState, string> = {
  idle: "Clip this page",
  clipping: "Clipping...",
  success: "Clipped!",
  error: "Retry",
};

const COLORS: Record<ClipState, string> = {
  idle: "#6366f1",
  clipping: "#6366f1",
  success: "#22c55e",
  error: "#ef4444",
};

export function ClipButton({ state, onClick, disabled }: Props) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || state === "clipping"}
      style={{
        width: "100%",
        padding: "10px",
        borderRadius: "8px",
        border: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        fontWeight: 600,
        fontSize: "14px",
        backgroundColor: COLORS[state],
        color: "white",
        opacity: disabled ? 0.5 : 1,
        transition: "background-color 0.15s, opacity 0.15s",
      }}
    >
      {LABELS[state]}
    </button>
  );
}
