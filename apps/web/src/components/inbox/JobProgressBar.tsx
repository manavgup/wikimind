interface JobProgressBarProps {
  pct: number;
  message?: string;
}

export function JobProgressBar({ pct, message }: JobProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(pct)));
  return (
    <div className="space-y-1">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full bg-brand-500 transition-all duration-300 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-slate-500">
        <span>{message || "Compiling..."}</span>
        <span>{clamped}%</span>
      </div>
    </div>
  );
}
