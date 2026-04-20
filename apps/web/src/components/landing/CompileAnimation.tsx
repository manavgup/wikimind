import { useEffect, useState } from "react";

interface CompileAnimationProps {
  onComplete: () => void;
}

const STAGES = [
  { label: "Authenticating", duration: 600 },
  { label: "Loading wiki", duration: 800 },
  { label: "Compiling index", duration: 700 },
  { label: "Ready", duration: 400 },
];

export function CompileAnimation({ onComplete }: CompileAnimationProps) {
  const [currentStage, setCurrentStage] = useState(0);

  useEffect(() => {
    if (currentStage >= STAGES.length) {
      const timer = setTimeout(onComplete, 300);
      return () => clearTimeout(timer);
    }

    const timer = setTimeout(() => {
      setCurrentStage((prev) => prev + 1);
    }, STAGES[currentStage].duration);

    return () => clearTimeout(timer);
  }, [currentStage, onComplete]);

  const progress = Math.min((currentStage / STAGES.length) * 100, 100);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950">
      <div className="w-full max-w-sm px-6 text-center">
        {/* Brain icon with pulse */}
        <div className="mb-8 flex justify-center">
          <div className="relative">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-900 text-3xl">
              &#x1f9e0;
            </div>
            <div className="absolute -inset-2 animate-ping rounded-2xl bg-brand-600/10" />
          </div>
        </div>

        {/* Progress bar */}
        <div className="mb-6 h-1 w-full overflow-hidden rounded-full bg-zinc-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400 transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Stage labels */}
        <div className="space-y-2">
          {STAGES.map((stage, i) => (
            <div
              key={stage.label}
              className={`flex items-center justify-center gap-2 text-sm transition-all duration-300 ${
                i < currentStage
                  ? "text-zinc-500"
                  : i === currentStage
                    ? "text-zinc-200"
                    : "text-zinc-700"
              }`}
            >
              {i < currentStage ? (
                <svg className="h-3.5 w-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
              ) : i === currentStage ? (
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-zinc-600 border-t-brand-400" />
              ) : (
                <span className="inline-block h-3.5 w-3.5" />
              )}
              {stage.label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
