import { useCallback, useState } from "react";
import type { ArticleResponse } from "../../types/api";
import { editArticle } from "../../api/wiki";

interface UseArticleEditorOptions {
  article: ArticleResponse;
  onArticleUpdated?: (article: ArticleResponse) => void;
}

export function useArticleEditor({ article, onArticleUpdated }: UseArticleEditorOptions) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleEdit = useCallback(() => {
    setEditContent(article.content ?? "");
    setSaveError(null);
    setIsEditing(true);
  }, [article.content]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setSaveError(null);
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      const updated = await editArticle(article.slug, { content: editContent });
      setIsEditing(false);
      onArticleUpdated?.(updated);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save changes.");
    } finally {
      setIsSaving(false);
    }
  }, [article.slug, editContent, onArticleUpdated]);

  return {
    isEditing,
    editContent,
    setEditContent,
    isSaving,
    saveError,
    handleEdit,
    handleCancel,
    handleSave,
  };
}
