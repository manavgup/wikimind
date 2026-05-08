import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSavedSearch,
  deleteSavedSearch,
  listSavedSearches,
} from "../../api/tags";

interface SavedSearchesProps {
  onExecute: (searchId: string) => void;
}

export function SavedSearches({ onExecute }: SavedSearchesProps) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");

  const { data: searches = [] } = useQuery({
    queryKey: ["saved-searches"],
    queryFn: listSavedSearches,
  });

  const createMutation = useMutation({
    mutationFn: () => createSavedSearch(name.trim(), query.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-searches"] });
      setName("");
      setQuery("");
      setShowCreate(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSavedSearch(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });

  return (
    <div className="border-t border-slate-200 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Saved Searches
        </h3>
        <button
          type="button"
          onClick={() => setShowCreate(!showCreate)}
          className="text-xs text-slate-400 hover:text-slate-700"
          title="Create a saved search"
        >
          +
        </button>
      </div>

      {showCreate ? (
        <div className="mb-2 space-y-1.5 rounded border border-slate-200 bg-slate-50 p-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Search name"
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:border-brand-400 focus:outline-none"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search query"
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:border-brand-400 focus:outline-none"
          />
          <div className="flex gap-1">
            <button
              type="button"
              disabled={!name.trim()}
              onClick={() => createMutation.mutate()}
              className="rounded bg-brand-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-40"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {searches.length === 0 ? (
        <p className="text-xs text-slate-400">No saved searches yet.</p>
      ) : (
        <ul className="space-y-0.5">
          {searches.map((s) => (
            <li
              key={s.id}
              className="group flex items-center justify-between rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
            >
              <button
                type="button"
                onClick={() => onExecute(s.id)}
                className="flex-1 truncate text-left text-xs"
                title={`Query: ${s.query || "(all)"}`}
              >
                {s.name}
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(s.id)}
                className="ml-1 hidden text-xs text-slate-400 hover:text-rose-500 group-hover:block"
                aria-label={`Delete saved search ${s.name}`}
              >
                x
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
