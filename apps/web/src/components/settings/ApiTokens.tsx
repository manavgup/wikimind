import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { apiFetch } from "../../api/client";

interface TokenCreateResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  name: string;
}

async function createApiToken(name: string, expiresInDays: number): Promise<TokenCreateResponse> {
  return apiFetch<TokenCreateResponse>("/auth/token", {
    method: "POST",
    body: { name, expires_in_days: expiresInDays },
  });
}

export function ApiTokens() {
  const [tokenName, setTokenName] = useState("api-token");
  const [expiryDays, setExpiryDays] = useState(90);
  const [generatedToken, setGeneratedToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const createMutation = useMutation({
    mutationFn: () => createApiToken(tokenName.trim() || "api-token", expiryDays),
    onSuccess: (data) => {
      setGeneratedToken(data.access_token);
    },
  });

  const handleCopy = async () => {
    if (!generatedToken) return;
    await navigator.clipboard.writeText(generatedToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleReset = () => {
    setGeneratedToken(null);
    setCopied(false);
    createMutation.reset();
  };

  return (
    <Card className="p-4">
      <p className="mb-3 text-sm text-slate-600">
        Generate tokens for Claude Desktop, MCP Inspector, the WikiMind browser
        extension, and any API client. Tokens use{" "}
        <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">
          Authorization: Bearer &lt;token&gt;
        </code>{" "}
        for authentication.
      </p>

      {generatedToken ? (
        <div>
          <p className="mb-2 text-xs font-semibold text-rose-600">
            Copy this token now. You will not be able to see it again.
          </p>
          <div className="mb-3 break-all rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-700">
            {generatedToken}
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCopy} size="sm">
              {copied ? "Copied!" : "Copy to Clipboard"}
            </Button>
            <Button variant="ghost" size="sm" onClick={handleReset}>
              Generate Another
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              Token name
            </label>
            <input
              type="text"
              value={tokenName}
              onChange={(e) => setTokenName(e.target.value)}
              placeholder="e.g. browser-extension"
              className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-brand-300 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              Expires in
            </label>
            <select
              value={expiryDays}
              onChange={(e) => setExpiryDays(Number(e.target.value))}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-brand-300 focus:outline-none"
            >
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
              <option value={365}>1 year</option>
            </select>
          </div>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? "Generating..." : "Generate Token"}
          </Button>
        </div>
      )}

      {createMutation.isError && (
        <p className="mt-2 text-xs text-rose-600">
          {createMutation.error instanceof Error
            ? createMutation.error.message
            : "Failed to create token"}
        </p>
      )}
    </Card>
  );
}
