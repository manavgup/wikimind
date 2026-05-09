import { useCallback, useEffect, useRef, useState } from "react";

interface InArticleSearchProps {
  /** ID of the DOM container whose text content to search. */
  containerId: string;
}

/**
 * In-article search bar triggered by Cmd/Ctrl+F.
 * Highlights all matches in the article body and navigates between them.
 */
export function InArticleSearch({ containerId }: InArticleSearchProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [matchCount, setMatchCount] = useState(0);
  const [currentMatch, setCurrentMatch] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Track open/close via Cmd+F
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 0);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
        setQuery("");
        clearHighlights();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  const clearHighlights = useCallback(() => {
    const container = document.getElementById(containerId);
    if (!container) return;
    const marks = container.querySelectorAll("mark.ias-highlight");
    marks.forEach((mark) => {
      const parent = mark.parentNode;
      if (parent) {
        parent.replaceChild(
          document.createTextNode(mark.textContent ?? ""),
          mark,
        );
        parent.normalize();
      }
    });
    setMatchCount(0);
    setCurrentMatch(0);
  }, [containerId]);

  const applyHighlights = useCallback(
    (searchText: string) => {
      clearHighlights();
      if (!searchText || searchText.length < 2) return;

      const container = document.getElementById(containerId);
      if (!container) return;

      const treeWalker = document.createTreeWalker(
        container,
        NodeFilter.SHOW_TEXT,
      );
      const textNodes: Text[] = [];
      let node: Node | null;
      while ((node = treeWalker.nextNode())) {
        textNodes.push(node as Text);
      }

      const lowerQuery = searchText.toLowerCase();
      let count = 0;

      for (const textNode of textNodes) {
        const text = textNode.textContent ?? "";
        const lowerText = text.toLowerCase();
        if (!lowerText.includes(lowerQuery)) continue;

        const fragment = document.createDocumentFragment();
        let lastIndex = 0;
        let idx = lowerText.indexOf(lowerQuery);

        while (idx !== -1) {
          if (idx > lastIndex) {
            fragment.appendChild(
              document.createTextNode(text.slice(lastIndex, idx)),
            );
          }
          const mark = document.createElement("mark");
          mark.className =
            "ias-highlight rounded-sm bg-amber-200/70 px-0.5 text-inherit";
          mark.dataset.matchIndex = String(count);
          mark.textContent = text.slice(idx, idx + searchText.length);
          fragment.appendChild(mark);
          count++;
          lastIndex = idx + searchText.length;
          idx = lowerText.indexOf(lowerQuery, lastIndex);
        }

        if (lastIndex < text.length) {
          fragment.appendChild(
            document.createTextNode(text.slice(lastIndex)),
          );
        }

        textNode.parentNode?.replaceChild(fragment, textNode);
      }

      setMatchCount(count);
      setCurrentMatch(count > 0 ? 1 : 0);

      // Scroll to first match
      if (count > 0) {
        scrollToMatch(0);
      }
    },
    [clearHighlights, containerId],
  );

  useEffect(() => {
    if (open) {
      applyHighlights(query);
    }
  }, [query, open, applyHighlights]);

  useEffect(() => {
    if (!open) {
      clearHighlights();
    }
  }, [open, clearHighlights]);

  const scrollToMatch = (index: number) => {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Reset all highlights to base style
    const marks = container.querySelectorAll("mark.ias-highlight");
    marks.forEach((m) => {
      (m as HTMLElement).className =
        "ias-highlight rounded-sm bg-amber-200/70 px-0.5 text-inherit";
    });

    // Highlight the current match
    const target = container.querySelector(
      `mark[data-match-index="${index}"]`,
    ) as HTMLElement | null;
    if (target) {
      target.className =
        "ias-highlight rounded-sm bg-orange-400/80 px-0.5 text-inherit ring-2 ring-orange-500/50";
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const goToNext = useCallback(() => {
    if (matchCount === 0) return;
    const next = currentMatch < matchCount ? currentMatch + 1 : 1;
    setCurrentMatch(next);
    scrollToMatch(next - 1);
  }, [currentMatch, matchCount]);

  const goToPrev = useCallback(() => {
    if (matchCount === 0) return;
    const prev = currentMatch > 1 ? currentMatch - 1 : matchCount;
    setCurrentMatch(prev);
    scrollToMatch(prev - 1);
  }, [currentMatch, matchCount]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (e.shiftKey) {
          goToPrev();
        } else {
          goToNext();
        }
      }
      if (e.key === "Escape") {
        setOpen(false);
        setQuery("");
      }
    },
    [goToNext, goToPrev],
  );

  if (!open) return null;

  return (
    <div
      className="fixed right-6 top-20 z-50 flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg"
      data-testid="in-article-search"
    >
      <svg
        className="h-4 w-4 text-slate-400"
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
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Find in article..."
        className="w-48 border-none bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
      />
      <span className="min-w-[4rem] text-center text-xs tabular-nums text-slate-500">
        {matchCount > 0
          ? `${currentMatch} / ${matchCount}`
          : query.length >= 2
            ? "0 results"
            : ""}
      </span>
      <button
        onClick={goToPrev}
        disabled={matchCount === 0}
        className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
        title="Previous match (Shift+Enter)"
      >
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4.5 15.75l7.5-7.5 7.5 7.5"
          />
        </svg>
      </button>
      <button
        onClick={goToNext}
        disabled={matchCount === 0}
        className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
        title="Next match (Enter)"
      >
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.5 8.25l-7.5 7.5-7.5-7.5"
          />
        </svg>
      </button>
      <button
        onClick={() => {
          setOpen(false);
          setQuery("");
        }}
        className="rounded p-1 text-slate-500 hover:bg-slate-100"
        title="Close (Esc)"
      >
        <svg
          className="h-3.5 w-3.5"
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
    </div>
  );
}
