import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useSearch } from "../../hooks/useArticles";
import { Spinner } from "../shared/Spinner";

const DEBOUNCE_MS = 300;

export function SearchBar() {
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [input]);

  const searchQuery = useSearch(debounced);
  const results = searchQuery.data ?? [];
  const showDropdown = open && debounced.trim().length >= 2;

  return (
    <div className="relative w-full">
      <input
        type="search"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        placeholder="Search articles..."
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />

      {showDropdown ? (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
          {searchQuery.isLoading ? (
            <div className="flex items-center gap-2 p-3 text-xs text-slate-500">
              <Spinner size={12} /> Searching...
            </div>
          ) : results.length === 0 ? (
            <div className="p-3 text-xs text-slate-500">No results</div>
          ) : (
            <ul className="py-1">
              {results.map((article) => (
                <li key={article.id}>
                  <Link
                    to={`/wiki/${encodeURIComponent(article.slug)}`}
                    className="block px-3 py-2 text-sm hover:bg-slate-50"
                    onMouseDown={(e) => e.preventDefault()}
                  >
                    <div className="font-medium text-slate-900">
                      {article.title}
                    </div>
                    {article.summary ? (
                      <div className="line-clamp-1 text-xs text-slate-500">
                        {article.summary}
                      </div>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
