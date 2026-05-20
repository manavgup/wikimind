import { useCallback, useState } from "react";
import { exportConversation } from "../../api/query";
import { useWebSocketStore } from "../../store/websocket";

interface UseExportConversationOptions {
  conversationId: string | undefined;
  conversationTitle: string | undefined;
}

export function useExportConversation({
  conversationId,
  conversationTitle,
}: UseExportConversationOptions) {
  const pushToast = useWebSocketStore((s) => s.pushToast);
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = useCallback(async () => {
    if (!conversationId) return;
    setIsExporting(true);
    try {
      const markdown = await exportConversation(conversationId);
      const blob = new Blob([markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const rawTitle = conversationTitle ?? "conversation";
      const safeName =
        rawTitle
          .replace(/[^a-zA-Z0-9_ -]/g, "")
          .replace(/ +/g, " ")
          .trim() || "conversation";
      a.download = safeName + ".md";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      pushToast({
        kind: "error",
        title: "Failed to export conversation",
        detail: "Could not download the markdown file.",
      });
    } finally {
      setIsExporting(false);
    }
  }, [conversationId, conversationTitle, pushToast]);

  return { handleExport, isExporting };
}
