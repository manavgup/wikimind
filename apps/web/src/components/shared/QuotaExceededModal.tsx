import { useNavigate } from "react-router-dom";
import { Button } from "./Button";

interface QuotaExceededModalProps {
  resource: string;
  onClose: () => void;
}

export function QuotaExceededModal({ resource, onClose }: QuotaExceededModalProps) {
  const navigate = useNavigate();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="mx-4 w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-lg">
        <h2 className="text-lg font-bold text-slate-900">Quota exceeded</h2>
        <p className="mt-2 text-sm text-slate-600">
          You&apos;ve reached the limit for <span className="font-medium">{resource}</span> on
          your current plan. Upgrade to Pro to continue.
        </p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={() => {
              onClose();
              navigate("/settings/billing");
            }}
          >
            Upgrade to Pro
          </Button>
        </div>
      </div>
    </div>
  );
}
