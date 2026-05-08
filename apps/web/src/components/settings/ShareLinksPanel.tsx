import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import {
  getPublicArticleUrl,
  listShareLinks,
  revokeShareLink,
} from "../../api/sharing";
import type { ShareLink } from "../../api/sharing";

export function ShareLinksPanel() {
  const queryClient = useQueryClient();

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

  const activeLinks = links.filter((l: ShareLink) => !l.revoked);

  if (isLoading) {
    return (
      <Card className="flex items-center justify-center p-6">
        <Spinner size={20} />
      </Card>
    );
  }

  if (activeLinks.length === 0) {
    return (
      <Card className="p-4">
        <p className="text-sm text-slate-500">
          No active share links. Use the Share button on any article to create one.
        </p>
      </Card>
    );
  }

  return (
    <Card className="divide-y divide-slate-100">
      {activeLinks.map((link: ShareLink) => (
        <div key={link.id} className="flex items-center gap-4 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-slate-800">
              {link.article_title ?? "Untitled"}
            </div>
            <div className="mt-0.5 truncate text-xs font-mono text-slate-400">
              {getPublicArticleUrl(link.token).replace(/^https?:\/\//, "")}
            </div>
            <div className="mt-0.5 text-xs text-slate-400">
              {link.view_count} view{link.view_count !== 1 ? "s" : ""}
              {link.expires_at
                ? ` · expires ${new Date(link.expires_at).toLocaleDateString()}`
                : ""}
              {" · created "}
              {new Date(link.created_at).toLocaleDateString()}
            </div>
          </div>
          <button
            onClick={() => revokeMutation.mutate(link.id)}
            disabled={revokeMutation.isPending}
            className="shrink-0 rounded border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
          >
            Revoke
          </button>
        </div>
      ))}
    </Card>
  );
}
