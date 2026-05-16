import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import {
  getPublicArticleUrl,
  listShareLinks,
  revokeShareLink,
} from "../../api/sharing";
import type { ShareLink } from "../../api/sharing";

export function ShareManagementView() {
  const queryClient = useQueryClient();
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const { data: links = [], isLoading } = useQuery({
    queryKey: ["share-links-all"],
    queryFn: () => listShareLinks(),
  });

  const revokeMutation = useMutation({
    mutationFn: (linkId: string) => revokeShareLink(linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["share-links-all"] });
    },
  });

  const handleCopy = useCallback(async (link: ShareLink) => {
    const url = getPublicArticleUrl(link.token);
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
    }
    setCopiedId(link.id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const activeLinks = links.filter((l: ShareLink) => !l.revoked);
  const revokedLinks = links.filter((l: ShareLink) => l.revoked);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6">
        <h1 className="mb-2 text-2xl font-bold text-slate-900">Share Links</h1>
        <p className="mb-6 text-sm text-slate-500">
          Manage all public share links for your wiki articles.
        </p>

        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-slate-700">
            Active ({activeLinks.length})
          </h2>
          {activeLinks.length === 0 ? (
            <Card className="p-4">
              <p className="text-sm text-slate-500">
                No active share links. Use the Share button on any article to
                create one.
              </p>
            </Card>
          ) : (
            <Card className="divide-y divide-slate-100">
              {activeLinks.map((link: ShareLink) => (
                <div
                  key={link.id}
                  className="flex items-center gap-4 px-4 py-3"
                  data-testid={`share-link-row-${link.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-800">
                      {link.article_title ?? "Untitled"}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
                      <span>
                        Created{" "}
                        {new Date(link.created_at).toLocaleDateString()}
                      </span>
                      <span>
                        {link.expires_at
                          ? `Expires ${new Date(link.expires_at).toLocaleDateString()}`
                          : "No expiry"}
                      </span>
                      <span>
                        {link.view_count} view
                        {link.view_count !== 1 ? "s" : ""}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => handleCopy(link)}
                    className="shrink-0 rounded border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                    data-testid={`copy-link-${link.id}`}
                  >
                    {copiedId === link.id ? "Copied!" : "Copy URL"}
                  </button>
                  <button
                    onClick={() => revokeMutation.mutate(link.id)}
                    disabled={revokeMutation.isPending}
                    className="shrink-0 rounded border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    data-testid={`revoke-link-${link.id}`}
                  >
                    Revoke
                  </button>
                </div>
              ))}
            </Card>
          )}
        </section>

        {revokedLinks.length > 0 && (
          <section>
            <h2 className="mb-3 text-lg font-semibold text-slate-700">
              Revoked ({revokedLinks.length})
            </h2>
            <Card className="divide-y divide-slate-100 opacity-60">
              {revokedLinks.map((link: ShareLink) => (
                <div
                  key={link.id}
                  className="flex items-center gap-4 px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-500 line-through">
                      {link.article_title ?? "Untitled"}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
                      <span>
                        Created{" "}
                        {new Date(link.created_at).toLocaleDateString()}
                      </span>
                      <span>
                        {link.view_count} view
                        {link.view_count !== 1 ? "s" : ""}
                      </span>
                      <span className="font-medium text-rose-400">Revoked</span>
                    </div>
                  </div>
                </div>
              ))}
            </Card>
          </section>
        )}
      </div>
    </div>
  );
}
