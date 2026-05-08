import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSearch } from "../../hooks/useArticles";
import { Spinner } from "../shared/Spinner";

const DEBOUNCE_MS = 300;
const RECENT_KEY = "wikimind-recent-searches";
const MAX_RECENT = 10;

function getRecentSearches(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function addRecentSearch(query: string): void {
  const recent = getRecentSearches().filter((s) => s !== query);
  recent.unshift(query);
  localStorage.setItem(
    RECENT_KEY,
    JSON.stringify(recent.slice(0, MAX_RECENT)),
  );
}

interface SearchBarProps {
  /** When provided, navigates to the search page with facets */
  onSearchSubmit?: (query: string) => void;
}

export function SearchBar({ onSearchSubmit }: SearchBarProps) {
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [showRecent, setShowRecent] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(input), DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [input]);

  const searchQuery = useSearch(debounced);
  const results = searchQuery.data ?? [];
  const showDropdown = open && debounced.trim().length >= 2;

  // Global "/" shortcut to focus
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (
        e.key === "/" &&
        !e.metaKey &&
        !e.ctrlKey &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Reset highlight when results change
  useEffect(() => {
    setHighlightIdx(-1);
  }, [results]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!showDropdown) {
        if (e.key === "Enter" && input.trim().length >= 2) {
          addRecentSearch(input.trim());
          onSearchSubmit?.(input.trim());
        }
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIdx((prev) => Math.min(prev + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIdx((prev) => Math.max(prev - 1, -1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (highlightIdx >= 0 && highlightIdx < results.length) {
          const article = results[highlightIdx];
          addRecentSearch(input.trim());
          navigate(`/wiki/${encodeURIComponent(article.slug)}`);
          setOpen(false);
        } else if (input.trim().length >= 2) {
          addRecentSearch(input.trim());
          onSearchSubmit?.(input.trim());
        }
      } else if (e.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    },
    [showDropdown, results, highlightIdx, input, navigate, onSearchSubmit],
  );

  const recentSearches = getRecentSearches();
  const showRecentDropdown =
    showRecent && !showDropdown && recentSearches.length > 0;

  return (
    <div className="relative w-full" data-testid="search-bar">
      <div className="relative">
        <svg
          className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          ref={inputRef}
          type="search"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setShowRecent(true);
          }}
          onBlur={() => {
            window.setTimeout(() => {
              setOpen(false);
              setShowRecent(false);
            }, 150);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search articles... ( / )"
          className="w-full rounded-md border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>

      {showRecentDropdown ? (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-60 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
          <div className="px-3 py-2 text-xs font-semibold text-slate-500">
            Recent Searches
          </div>
          <ul className="py-1">
            {recentSearches.map((term) => (
              <li key={term}>
                <button
                  className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    setInput(term);
                    setDebounced(term);
                    onSearchSubmit?.(term);
                  }}
                >
                  <svg
                    className="mr-2 inline h-3.5 w-3.5 text-slate-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  {term}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {showDropdown ? (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 max-h-80 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg">
          {searchQuery.isLoading ? (
            <div className="flex items-center gap-2 p-3 text-xs text-slate-500">
              <Spinner size={12} /> Searching...
            </div>
          ) : results.length === 0 ? (
            <div className="p-3 text-xs text-slate-500">No results</div>
          ) : (
            <>
              <ul className="py-1">
                {results.map((article, idx) => (
                  <li key={article.id}>
                    <Link
                      to={`/wiki/${encodeURIComponent(article.slug)}`}
                      className={`block px-3 py-2 text-sm ${
                        idx === highlightIdx
                          ? "bg-brand-50 text-brand-900"
                          : "hover:bg-slate-50"
                      }`}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setHighlightIdx(idx)}
                      onClick={() => addRecentSearch(input.trim())}
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
              {onSearchSubmit && input.trim().length >= 2 && (
                <div className="border-t border-slate-100 px-3 py-2">
                  <button
                    className="w-full rounded-md bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      addRecentSearch(input.trim());
                      onSearchSubmit(input.trim());
                    }}
                  >
                    View all results for "{input.trim()}"
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
