import { createContext, useContext, useState, useCallback } from "react";
import type { ReactNode } from "react";

export interface CitationTarget {
  sourceId: string;
  spanText: string;
  sourceName: string | null;
  locatorInfo: string;
}

interface CitationContextValue {
  /** The citation currently being viewed in the source panel. */
  activeCitation: CitationTarget | null;
  /** Open the source panel with a highlighted span. */
  showCitation: (target: CitationTarget) => void;
  /** Clear the active citation (back to default sidebar). */
  clearCitation: () => void;
}

const CitationCtx = createContext<CitationContextValue | null>(null);

export function CitationProvider({ children }: { children: ReactNode }) {
  const [activeCitation, setActiveCitation] = useState<CitationTarget | null>(
    null,
  );

  const showCitation = useCallback((target: CitationTarget) => {
    setActiveCitation(target);
  }, []);

  const clearCitation = useCallback(() => {
    setActiveCitation(null);
  }, []);

  return (
    <CitationCtx.Provider
      value={{ activeCitation, showCitation, clearCitation }}
    >
      {children}
    </CitationCtx.Provider>
  );
}

export function useCitation(): CitationContextValue {
  const ctx = useContext(CitationCtx);
  if (!ctx) {
    throw new Error("useCitation must be used within a CitationProvider");
  }
  return ctx;
}
