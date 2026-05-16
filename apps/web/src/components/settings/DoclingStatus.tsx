import { useQuery } from "@tanstack/react-query";
import { Badge } from "../shared/Badge";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { getDoclingStatus } from "../../api/admin";

export function DoclingStatus() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["docling-status"],
    queryFn: getDoclingStatus,
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return (
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <Spinner size={16} />
          <span className="text-sm text-slate-500">Checking Docling status...</span>
        </div>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="p-4">
        <div className="mb-4 flex items-center justify-between">
          <span className="font-semibold text-slate-700">Docling (PDF Processing)</span>
          <Badge tone="neutral">Unknown</Badge>
        </div>
        <p className="text-sm text-slate-500">Unable to check Docling status.</p>
      </Card>
    );
  }

  const isConnected = data.status === "connected";

  return (
    <Card className="p-4">
      <div className="mb-4 flex items-center justify-between">
        <span className="font-semibold text-slate-700">Docling (PDF Processing)</span>
        <Badge tone={isConnected ? "success" : "danger"}>
          {isConnected ? "Connected" : "Disconnected"}
        </Badge>
      </div>

      <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <span className="text-slate-500">Status</span>
        <span className="flex items-center gap-2 text-slate-700">
          <span
            className={`inline-block h-2 w-2 rounded-full ${isConnected ? "bg-emerald-500" : "bg-rose-500"}`}
          />
          {isConnected ? "Connected" : "Disconnected"}
        </span>

        <span className="text-slate-500">URL</span>
        <span className="font-mono text-slate-700">{data.url}</span>

        <span className="text-slate-500">Latency</span>
        <span className="text-slate-700">
          {data.latency_ms !== null ? `${data.latency_ms} ms` : "N/A"}
        </span>
      </div>

      {!isConnected && (
        <p className="mt-4 text-xs text-slate-400">
          Set WIKIMIND_DOCLING_SERVE_URL to the docling-serve sidecar address.
        </p>
      )}
    </Card>
  );
}
