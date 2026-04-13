import { useState } from "react";
import { useParams } from "react-router-dom";
import { useArticle } from "../../hooks/useArticle";
import { Spinner } from "../shared/Spinner";
import { ArticleCardGrid } from "./ArticleCardGrid";
import { ArticleReader } from "./ArticleReader";
import { BacklinkPanel } from "./BacklinkPanel";
import { ConceptTree } from "./ConceptTree";
import { FiguresPanel } from "./FiguresPanel";
import { SearchBar } from "./SearchBar";

export function WikiExplorerView() {
  const params = useParams<{ slug?: string }>();
  const slug = params.slug;
  const articleQuery = useArticle(slug);
  const [activeConcept, setActiveConcept] = useState<string | null>(null);
  const [figureCount, setFigureCount] = useState(0);

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

      {slug ? (
        <div className="grid flex-1 grid-cols-[15rem_1fr_15rem] overflow-hidden">
          <aside className="overflow-y-auto border-r border-slate-200 bg-white">
            <ConceptTree
              activeConcept={activeConcept}
              onSelectConcept={setActiveConcept}
            />
          </aside>

          <section className="overflow-y-auto bg-slate-50">
            {articleQuery.isLoading ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                <Spinner size={16} /> Loading article...
              </div>
            ) : articleQuery.isError ? (
              <div className="m-8 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
                Failed to load article.
              </div>
            ) : articleQuery.data ? (
              <>
                <ArticleReader article={articleQuery.data} />
                {articleQuery.data.sources && (
                  <FiguresPanel
                    sources={articleQuery.data.sources}
                    onImageCount={setFigureCount}
                  />
                )}
              </>
            ) : null}
          </section>

          <aside className="overflow-y-auto border-l border-slate-200 bg-white">
            <BacklinkPanel
              article={articleQuery.data ?? null}
              hasFigures={figureCount > 0}
              figureCount={figureCount}
            />
          </aside>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-[15rem_1fr] overflow-hidden">
          <aside className="overflow-y-auto border-r border-slate-200 bg-white">
            <ConceptTree
              activeConcept={activeConcept}
              onSelectConcept={setActiveConcept}
            />
          </aside>

          <section className="overflow-y-auto bg-slate-50">
            <ArticleCardGrid activeConcept={activeConcept} />
          </section>
        </div>
      )}
    </div>
  );
}
