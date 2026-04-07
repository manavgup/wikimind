import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { getArticle } from "../api/wiki";
import type { ArticleResponse } from "../types/api";

export function useArticle(
  slug: string | undefined,
): UseQueryResult<ArticleResponse> {
  return useQuery({
    queryKey: ["article", slug],
    queryFn: () => getArticle(slug as string),
    enabled: Boolean(slug),
  });
}
