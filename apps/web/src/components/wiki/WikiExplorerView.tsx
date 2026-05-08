import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useArticle } from "../../hooks/useArticle";
import { getRandomArticle } from "../../api/wiki";
import { Spinner } from "../shared/Spinner";
import { ArticleCardGrid } from "./ArticleCardGrid";
import { ArticleOutline } from "./ArticleOutline";
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
  const navigate = useNavigate();

  const handleRandomArticle = async () => {
    try {
      const article = await getRandomArticle();
      navigate(`/wiki/${encodeURIComponent(article.slug)}`);
    } catch {
      // No articles available — silently ignore
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold text-slate-900">Wiki</h1>
          <div className="max-w-md flex-1">
            <SearchBar />
          </div>
          <button
            type="button"
            onClick={handleRandomArticle}
            className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 shadow-sm transition hover:bg-slate-50 hover:text-slate-900"
            title="Open a random article"
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
                d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 0 0-3.7-3.7 48.678 48.678 0 0 0-7.324 0 4.006 4.006 0 0 0-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3-3-3m-12 3c0 1.232.046 2.453.138 3.662a4.006 4.006 0 0 0 3.7 3.7 48.656 48.656 0 0 0 7.324 0 4.006 4.006 0 0 0 3.7-3.7c.017-.22.032-.441.046-.662M4.5 12l3 3m-3-3-3 3"
              />
            </svg>
            Random
          </button>
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
            {articleQuery.data ? (
              <div className="flex h-full flex-col">
                <div className="border-b border-slate-200 px-4">
                  <ArticleOutline content={articleQuery.data.content ?? ""} />
                </div>
                <div className="flex-1 overflow-y-auto">
                  <BacklinkPanel
                    article={articleQuery.data}
                    hasFigures={figureCount > 0}
                    figureCount={figureCount}
                  />
                </div>
              </div>
            ) : (
              <BacklinkPanel
                article={null}
                hasFigures={false}
                figureCount={0}
              />
            )}
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
