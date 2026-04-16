import { Badge } from "../shared/Badge";
import { Card } from "../shared/Card";

interface SyncStatusProps {
  sync: {
    enabled: boolean;
    interval_minutes: number;
    bucket: string | null;
  };
}

export function SyncStatus({ sync }: SyncStatusProps) {
  return (
    <Card className="p-4">
      <div className="mb-4 flex items-center justify-between">
        <span className="font-semibold text-slate-700">Sync</span>
        <Badge tone={sync.enabled ? "success" : "neutral"}>
          {sync.enabled ? "Enabled" : "Disabled"}
        </Badge>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <span className="text-slate-500">Status</span>
        <span className="text-slate-700">{sync.enabled ? "Enabled" : "Not configured"}</span>

        <span className="text-slate-500">Interval</span>
        <span className="text-slate-700">Every {sync.interval_minutes} minutes</span>

        <span className="text-slate-500">Bucket</span>
        {sync.bucket ? (
          <span className="text-slate-700">{sync.bucket}</span>
        ) : (
          <span className="italic text-slate-400">Not set</span>
        )}

        <span className="text-slate-500">Last sync</span>
        <span className="italic text-slate-400">Never</span>
      </div>

      <p className="mt-4 text-xs text-slate-400">
        Configure sync in your .env file (WIKIMIND_SYNC__ENABLED=true)
      </p>
    </Card>
  );
}
