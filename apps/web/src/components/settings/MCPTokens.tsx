import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { apiFetch } from "../../api/client";

interface MCPToken {
  id: string;
  name: string;
  token_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface MCPTokenCreateResponse {
  id: string;
  token: string;
  name: string;
  created_at: string;
}

function listMCPTokens(): Promise<MCPToken[]> {
  return apiFetch<MCPToken[]>("/api/settings/mcp-tokens");
}

function createMCPToken(name: string): Promise<MCPTokenCreateResponse> {
  return apiFetch<MCPTokenCreateResponse>("/api/settings/mcp-tokens", {
    method: "POST",
    body: { name },
  });
}

function revokeMCPToken(tokenId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/settings/mcp-tokens/${tokenId}`, {
    method: "DELETE",
  });
}

export function MCPTokens() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const queryClient = useQueryClient();

  const { data: tokens, isLoading } = useQuery({
    queryKey: ["mcp-tokens"],
    queryFn: listMCPTokens,
  });

  const createMutation = useMutation({
    mutationFn: createMCPToken,
    onSuccess: (data) => {
      setNewToken(data.token);
      setTokenName("");
      queryClient.invalidateQueries({ queryKey: ["mcp-tokens"] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: revokeMCPToken,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-tokens"] });
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (tokenName.trim()) {
      createMutation.mutate(tokenName.trim());
    }
  };

  const handleCopy = async () => {
    if (newToken) {
      await navigator.clipboard.writeText(newToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleCloseModal = () => {
    setShowCreateModal(false);
    setNewToken(null);
    setTokenName("");
    setCopied(false);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  if (isLoading) {
    return (
      <Card className="p-4">
        <div className="flex items-center justify-center py-4">
          <Spinner size={20} />
        </div>
      </Card>
    );
  }

  const activeTokens = tokens?.filter((t) => !t.revoked) ?? [];
  const revokedTokens = tokens?.filter((t) => t.revoked) ?? [];

  return (
    <>
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-sm text-slate-500">
            Personal access tokens for MCP clients like Claude Desktop.
          </p>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
          >
            Generate Token
          </Button>
        </div>

        {activeTokens.length === 0 && revokedTokens.length === 0 ? (
          <p className="py-4 text-center text-sm text-slate-400">
            No tokens yet. Generate one to connect MCP clients.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Token</th>
                <th className="pb-2 font-medium">Created</th>
                <th className="pb-2 font-medium">Last used</th>
                <th className="pb-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {activeTokens.map((token) => (
                <tr
                  key={token.id}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="py-2 text-slate-700">{token.name}</td>
                  <td className="py-2">
                    <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                      {token.token_prefix}...
                    </code>
                  </td>
                  <td className="py-2 text-slate-500">
                    {formatDate(token.created_at)}
                  </td>
                  <td className="py-2 text-slate-500">
                    {token.last_used_at
                      ? formatDate(token.last_used_at)
                      : "Never"}
                  </td>
                  <td className="py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => revokeMutation.mutate(token.id)}
                      disabled={revokeMutation.isPending}
                    >
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
              {revokedTokens.map((token) => (
                <tr
                  key={token.id}
                  className="border-b border-slate-100 opacity-50 last:border-0"
                >
                  <td className="py-2 text-slate-400 line-through">
                    {token.name}
                  </td>
                  <td className="py-2">
                    <code className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-400">
                      {token.token_prefix}...
                    </code>
                  </td>
                  <td className="py-2 text-slate-400">
                    {formatDate(token.created_at)}
                  </td>
                  <td className="py-2 text-slate-400">Revoked</td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Create / reveal modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            {newToken ? (
              <>
                <h3 className="mb-2 text-lg font-semibold text-slate-900">
                  Token Created
                </h3>
                <p className="mb-3 text-sm text-amber-600">
                  Copy this token now. It will not be shown again.
                </p>
                <div className="mb-4 flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-slate-100 px-3 py-2 text-sm text-slate-800">
                    {newToken}
                  </code>
                  <Button variant="primary" size="sm" onClick={handleCopy}>
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
                <div className="flex justify-end">
                  <Button variant="ghost" size="sm" onClick={handleCloseModal}>
                    Done
                  </Button>
                </div>
              </>
            ) : (
              <form onSubmit={handleCreate}>
                <h3 className="mb-4 text-lg font-semibold text-slate-900">
                  Generate MCP Token
                </h3>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  Token name
                </label>
                <input
                  type="text"
                  value={tokenName}
                  onChange={(e) => setTokenName(e.target.value)}
                  placeholder="e.g. Claude Desktop"
                  className="mb-4 w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-brand-300 focus:outline-none"
                  maxLength={100}
                  autoFocus
                />
                <div className="flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    type="button"
                    onClick={handleCloseModal}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    type="submit"
                    disabled={!tokenName.trim() || createMutation.isPending}
                  >
                    {createMutation.isPending ? "Generating..." : "Generate"}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
