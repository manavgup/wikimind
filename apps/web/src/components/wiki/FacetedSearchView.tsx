import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useFacetedSearch, useSearchFacets } from "../../hooks/useArticles";
import { Badge } from "../shared/Badge";
import { Spinner } from "../shared/Spinner";
import { FacetSidebar } from "./FacetSidebar";
import { SearchBar } from "./SearchBar";

const SORT_OPTIONS = [
  { value: "relevance", label: "Relevance" },
  { value: "recency", label: "Most Recent" },
];

export function FacetedSearchView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const sort = searchParams.get("sort") ?? "relevance";

  // Active facet filters from URL params
  const activeFilters: Record<string, string> = {};
  for (const key of [
    "source_kind",
    "page_type",
    "concept",
    "tag",
    "date_range",
    "staleness",
  ]) {
    const val = searchParams.get(key);
    if (val) activeFilters[key] = val;
  }

  const facetsQuery = useSearchFacets(query);
  const searchQuery = useFacetedSearch(
    query.length >= 2
      ? {
          q: query,
          ...activeFilters,
          sort,
          limit: 50,
        }
      : null,
  );

  const handleSearchSubmit = useCallback(
    (q: string) => {
      const params = new URLSearchParams(searchParams);
      params.set("q", q);
      setSearchParams(params);
    },
    [searchParams, setSearchParams],
  );

  const handleFilterChange = useCallback(
    (name: string, value: string | null) => {
      const params = new URLSearchParams(searchParams);
      // Map facet names to query param names
      const paramKey = name === "date" ? "date_range" : name;
      if (value) {
        params.set(paramKey, value);
      } else {
        params.delete(paramKey);
      }
      setSearchParams(params);
    },
    [searchParams, setSearchParams],
  );

  const handleSortChange = useCallback(
    (newSort: string) => {
      const params = new URLSearchParams(searchParams);
      params.set("sort", newSort);
      setSearchParams(params);
    },
    [searchParams, setSearchParams],
  );

  const results = searchQuery.data?.results ?? [];
  const total = searchQuery.data?.total ?? 0;
  const facets = facetsQuery.data?.facets ?? [];

  // Remap date_range filter key to "date" for the sidebar component
  const sidebarFilters: Record<string, string> = {};
  for (const [k, v] of Object.entries(activeFilters)) {
    sidebarFilters[k === "date_range" ? "date" : k] = v;
  }

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="faceted-search-view">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-4">
          <Link
            to="/wiki"
            className="text-lg font-semibold text-slate-900 hover:text-brand-700"
          >
            Wiki
          </Link>
          <div className="max-w-lg flex-1">
            <SearchBar onSearchSubmit={handleSearchSubmit} />
          </div>
        </div>
      </header>

      {query.length < 2 ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-md text-center">
            <svg
              className="mx-auto mb-4 h-12 w-12 text-slate-300"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
              />
            </svg>
            <h2 className="text-lg font-semibold text-slate-700">
              Search your wiki
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Type at least 2 characters to start searching. Use filters to
              narrow results by source type, concept, tag, and more.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-[16rem_1fr] overflow-hidden">
          {/* Facet sidebar */}
          <aside className="overflow-y-auto border-r border-slate-200 bg-white">
            {facetsQuery.isLoading ? (
              <div className="flex items-center gap-2 p-4 text-xs text-slate-500">
                <Spinner size={12} /> Loading filters...
              </div>
            ) : (
              <FacetSidebar
                facets={facets}
                activeFilters={sidebarFilters}
                onFilterChange={handleFilterChange}
              />
            )}
          </aside>

          {/* Results */}
          <section className="overflow-y-auto bg-slate-50">
            <div className="border-b border-slate-200 bg-white px-6 py-3">
              <div className="flex items-center justify-between">
                <div className="text-sm text-slate-600">
                  {searchQuery.isLoading ? (
                    <span className="flex items-center gap-2">
                      <Spinner size={12} /> Searching...
                    </span>
                  ) : (
                    <span>
                      <strong className="font-semibold text-slate-900">
                        {total}
                      </strong>{" "}
                      {total === 1 ? "result" : "results"} for{" "}
                      <strong className="font-semibold text-slate-900">
                        "{query}"
                      </strong>
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <label
                    htmlFor="sort-select"
                    className="text-xs text-slate-500"
                  >
                    Sort by:
                  </label>
                  <select
                    id="sort-select"
                    value={sort}
                    onChange={(e) => handleSortChange(e.target.value)}
                    className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Active filter pills */}
              {Object.keys(activeFilters).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(activeFilters).map(([key, value]) => (
                    <button
                      key={key}
                      onClick={() => handleFilterChange(key === "date_range" ? "date" : key, null)}
                      className="group inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700 transition hover:border-brand-300 hover:bg-brand-100"
                    >
                      <span className="text-brand-500">{key.replace("_", " ")}:</span>
                      {value}
                      <svg
                        className="h-3 w-3 text-brand-400 group-hover:text-brand-600"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={2}
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {searchQuery.isLoading ? null : results.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16">
                <svg
                  className="mb-3 h-10 w-10 text-slate-300"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9zm3.75 11.625a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
                  />
                </svg>
                <p className="text-sm font-medium text-slate-700">
                  No results found
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Try different keywords or remove some filters.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {results.map((result) => (
                  <li key={result.article_id}>
                    <Link
                      to={`/wiki/${encodeURIComponent(result.slug)}`}
                      className="block px-6 py-4 transition hover:bg-white"
                    >
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-slate-900">
                          {result.title}
                        </h3>
                        <Badge tone="neutral">{result.slug}</Badge>
                      </div>
                      {result.snippet && (
                        <p
                          className="mt-1 line-clamp-2 text-xs text-slate-500"
                          dangerouslySetInnerHTML={{ __html: result.snippet }}
                        />
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
