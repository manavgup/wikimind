import { useParams } from "react-router-dom";
import { useArticle } from "../../hooks/useArticle";
import { Spinner } from "../shared/Spinner";
import { ArticleReader } from "./ArticleReader";
import { BacklinkPanel } from "./BacklinkPanel";
import { ConceptTree } from "./ConceptTree";
import { SearchBar } from "./SearchBar";

export function WikiExplorerView() {
  const params = useParams<{ slug?: string }>();
  const slug = params.slug;
  const articleQuery = useArticle(slug);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold text-slate-900">Wiki</h1>
          <div className="max-w-md flex-1">
            <SearchBar />
          </div>
        </div>
      </header>

      <div className="grid flex-1 grid-cols-[15rem_1fr_15rem] overflow-hidden">
        <aside className="overflow-y-auto border-r border-slate-200 bg-white">
          <ConceptTree selectedSlug={slug} />
        </aside>

        <section className="overflow-y-auto bg-slate-50">
          {!slug ? (
            <EmptyArticleState />
          ) : articleQuery.isLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
              <Spinner size={16} /> Loading article...
            </div>
          ) : articleQuery.isError ? (
            <div className="m-8 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
              Failed to load article.
            </div>
          ) : articleQuery.data ? (
            <ArticleReader article={articleQuery.data} />
          ) : null}
        </section>

        <aside className="overflow-y-auto border-l border-slate-200 bg-white">
          <BacklinkPanel article={articleQuery.data ?? null} />
        </aside>
      </div>
    </div>
  );
}

function EmptyArticleState() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-md text-center">
        <div className="mb-3 text-4xl">📚</div>
        <h2 className="text-lg font-semibold text-slate-800">Pick an article</h2>
        <p className="mt-1 text-sm text-slate-500">
          Choose a concept on the left, search above, or open one of the recent
          articles to start reading.
        </p>
      </div>
    </div>
  );
}
