import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createShareLink,
  getPublicArticleUrl,
  listShareLinks,
  revokeShareLink,
} from "../../api/sharing";
import type { ShareLink } from "../../api/sharing";

const EXPIRY_OPTIONS: { label: string; value: number | null }[] = [
  { label: "1 day", value: 1 },
  { label: "7 days", value: 7 },
  { label: "30 days", value: 30 },
  { label: "Never", value: null },
];

interface ShareButtonProps {
  articleId: string;
}

export function ShareButton({ articleId }: ShareButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [expiryDays, setExpiryDays] = useState<number | null>(7);
  const queryClient = useQueryClient();

  const { data: links = [] } = useQuery({
    queryKey: ["share-links", articleId],
    queryFn: () => listShareLinks(articleId),
    enabled: isOpen,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createShareLink({
        article_id: articleId,
        expires_in_days: expiryDays,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["share-links", articleId] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (linkId: string) => revokeShareLink(linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["share-links", articleId] });
    },
  });

  const handleCopy = useCallback(async (token: string) => {
    const url = getPublicArticleUrl(token);
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-secure contexts
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, []);

  const activeLinks = links.filter((l: ShareLink) => !l.revoked);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        data-testid="share-button"
      >
        <svg
          className="h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M7.217 10.907a2.25 2.25 0 1 0 0 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186 9.566-5.314m-9.566 7.5 9.566 5.314m0 0a2.25 2.25 0 1 0 3.935 2.186 2.25 2.25 0 0 0-3.935-2.186Zm0-12.814a2.25 2.25 0 1 0 3.933-2.185 2.25 2.25 0 0 0-3.933 2.185Z"
          />
        </svg>
        Share
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border border-slate-200 bg-white p-4 shadow-lg">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">
              Share Links
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="text-slate-400 hover:text-slate-600"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {activeLinks.length > 0 ? (
            <div className="mb-3 space-y-2">
              {activeLinks.map((link: ShareLink) => (
                <div
                  key={link.id}
                  className="flex items-center gap-2 rounded-md border border-slate-100 bg-slate-50 p-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-mono text-slate-600">
                      {getPublicArticleUrl(link.token).replace(/^https?:\/\//, "")}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">
                      {link.view_count} view{link.view_count !== 1 ? "s" : ""}
                      {link.expires_at
                        ? ` · expires ${new Date(link.expires_at).toLocaleDateString()}`
                        : " · no expiry"}
                    </div>
                  </div>
                  <button
                    onClick={() => handleCopy(link.token)}
                    className="shrink-0 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                    title="Copy link"
                  >
                    {copied ? "Copied!" : "Copy"}
                  </button>
                  <button
                    onClick={() => revokeMutation.mutate(link.id)}
                    disabled={revokeMutation.isPending}
                    className="shrink-0 rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    title="Revoke link"
                  >
                    Revoke
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mb-3 text-sm text-slate-500">
              No active share links for this article.
            </p>
          )}

          <div className="mb-3">
            <label className="mb-1 block text-xs font-medium text-slate-600">
              Link expiry
            </label>
            <div className="flex gap-1">
              {EXPIRY_OPTIONS.map((opt) => (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => setExpiryDays(opt.value)}
                  className={`rounded-md px-2 py-1 text-xs font-medium transition ${
                    expiryDays === opt.value
                      ? "bg-brand-100 text-brand-700 ring-1 ring-brand-300"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                  data-testid={`expiry-option-${opt.label.toLowerCase().replace(/\s/g, "-")}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            className="w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            data-testid="create-share-link"
          >
            {createMutation.isPending ? "Creating..." : "Create Share Link"}
          </button>
        </div>
      )}
    </div>
  );
}
