import { useEffect, useState } from "react";

interface CompileAnimationProps {
  onComplete: () => void;
}

const STAGES = [
  "authenticating\u2026",
  "loading your wiki\u2026",
  "indexing 214 sources\u2026",
  "almost there\u2026",
];

export function CompileAnimation({ onComplete }: CompileAnimationProps) {
  const [statusText, setStatusText] = useState(STAGES[0]);

  useEffect(() => {
    let i = 0;
    const tick = () => {
      if (i < STAGES.length) {
        setStatusText(STAGES[i]);
        i++;
        setTimeout(tick, 520);
      } else {
        onComplete();
      }
    };
    tick();
  }, [onComplete]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-white">
      <div
        className="h-8 w-8 rounded-full border-[3px] border-slate-200 animate-spin-custom"
        style={{ borderTopColor: "#365b91" }}
        aria-hidden="true"
      />
      <div
        className="text-[13px] text-slate-700"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {statusText}
      </div>
    </div>
  );
}
