import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { TagRef } from "../../types/api";
import { createTag, listTags, tagArticle, untagArticle } from "../../api/tags";
import { TagPill } from "../shared/TagPill";

const PRESET_COLORS = [
  "#6366f1", // indigo
  "#ef4444", // red
  "#f59e0b", // amber
  "#22c55e", // green
  "#3b82f6", // blue
  "#a855f7", // purple
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#64748b", // slate
];

interface TagSelectorProps {
  articleId: string;
  currentTags: TagRef[];
  onTagsChanged?: () => void;
}

export function TagSelector({
  articleId,
  currentTags,
  onTagsChanged,
}: TagSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [selectedColor, setSelectedColor] = useState(PRESET_COLORS[0]);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: allTags = [] } = useQuery({
    queryKey: ["tags"],
    queryFn: listTags,
  });

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) return undefined;
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () =>
      document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const currentTagIds = new Set(currentTags.map((t) => t.id));
  const availableTags = allTags.filter((t) => !currentTagIds.has(t.id));

  const invalidateTags = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["tags"] });
    onTagsChanged?.();
  }, [queryClient, onTagsChanged]);

  const addTagMutation = useMutation({
    mutationFn: (tagId: string) => tagArticle(articleId, tagId),
    onSuccess: invalidateTags,
  });

  const removeTagMutation = useMutation({
    mutationFn: (tagId: string) => untagArticle(articleId, tagId),
    onSuccess: invalidateTags,
  });

  const createAndAddMutation = useMutation({
    mutationFn: async () => {
      const tag = await createTag(newTagName.trim(), selectedColor);
      await tagArticle(articleId, tag.id);
      return tag;
    },
    onSuccess: () => {
      setNewTagName("");
      invalidateTags();
    },
  });

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {currentTags.map((tag) => (
        <TagPill
          key={tag.id}
          name={tag.name}
          color={tag.color}
          onRemove={() => removeTagMutation.mutate(tag.id)}
        />
      ))}

      <div className="relative" ref={dropdownRef}>
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700"
        >
          + Tag
        </button>

        {isOpen ? (
          <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
            {availableTags.length > 0 ? (
              <div className="mb-2">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Existing tags
                </p>
                <div className="flex flex-wrap gap-1">
                  {availableTags.map((tag) => (
                    <TagPill
                      key={tag.id}
                      name={tag.name}
                      color={tag.color}
                      onClick={() => {
                        addTagMutation.mutate(tag.id);
                        setIsOpen(false);
                      }}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            <div className="border-t border-slate-100 pt-2">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Create new
              </p>
              <input
                type="text"
                value={newTagName}
                onChange={(e) => setNewTagName(e.target.value)}
                placeholder="Tag name"
                className="mb-1.5 w-full rounded border border-slate-200 px-2 py-1 text-xs focus:border-brand-400 focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newTagName.trim()) {
                    createAndAddMutation.mutate();
                    setIsOpen(false);
                  }
                }}
              />
              <div className="mb-1.5 flex flex-wrap gap-1">
                {PRESET_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setSelectedColor(c)}
                    className={`h-4 w-4 rounded-full border-2 ${
                      selectedColor === c
                        ? "border-slate-800"
                        : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                    aria-label={`Select color ${c}`}
                  />
                ))}
              </div>
              <button
                type="button"
                disabled={!newTagName.trim()}
                onClick={() => {
                  createAndAddMutation.mutate();
                  setIsOpen(false);
                }}
                className="w-full rounded bg-brand-600 px-2 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-40"
              >
                Create & Add
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
