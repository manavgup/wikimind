import { useCallback, useEffect, useRef, useState } from "react";
import type { DiscussionMessage, DiscussionThread } from "../../api/wiki";
import {
  compileWithGuidance,
  getDiscussionThread,
  postDiscussionMessage,
} from "../../api/wiki";

interface DiscussionPanelProps {
  articleId: string;
}

export function DiscussionPanel({ articleId }: DiscussionPanelProps) {
  const [messages, setMessages] = useState<DiscussionMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadThread = useCallback(async () => {
    try {
      const thread: DiscussionThread =
        await getDiscussionThread(articleId);
      setMessages(thread.messages);
    } catch {
      // No thread yet -- that's fine
    }
  }, [articleId]);

  useEffect(() => {
    if (open) {
      loadThread();
    }
  }, [open, loadThread]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userMessage = input.trim();
    setInput("");
    setError(null);

    // Optimistic update: show user message immediately
    const tempUserMsg: DiscussionMessage = {
      id: `temp-${Date.now()}`,
      article_id: articleId,
      role: "user",
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setLoading(true);

    try {
      const response = await postDiscussionMessage(articleId, userMessage);
      // Replace temp message with real messages from server
      await loadThread();
      void response; // response is the assistant message, thread reload handles it
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to send message",
      );
      // Remove the optimistic message on error
      setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
    } finally {
      setLoading(false);
    }
  };

  const handleCompile = async () => {
    setCompiling(true);
    setError(null);
    try {
      const result = await compileWithGuidance(articleId);
      setError(null);
      alert(`Recompilation queued (job ${result.job_id}). The article will be updated shortly.`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to trigger recompilation",
      );
    } finally {
      setCompiling(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md
                   bg-indigo-50 text-indigo-700 hover:bg-indigo-100
                   dark:bg-indigo-900/30 dark:text-indigo-300
                   dark:hover:bg-indigo-900/50 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
          />
        </svg>
        Discuss before recompiling
      </button>
    );
  }

  return (
    <div className="border rounded-lg bg-white dark:bg-gray-900 dark:border-gray-700 mt-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Discussion
        </h3>
        <button
          onClick={() => setOpen(false)}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          title="Close discussion"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="max-h-80 overflow-y-auto px-4 py-3 space-y-3"
      >
        {messages.length === 0 && !loading && (
          <p className="text-sm text-gray-500 dark:text-gray-400 italic">
            Ask questions about the sources or suggest what the article should
            focus on. When you're ready, click "Recompile with guidance" to
            incorporate your feedback.
          </p>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`text-sm rounded-lg px-3 py-2 max-w-[85%] ${
              msg.role === "user"
                ? "ml-auto bg-indigo-100 dark:bg-indigo-900/40 text-indigo-900 dark:text-indigo-100"
                : "mr-auto bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200"
            }`}
          >
            <p className="whitespace-pre-wrap">{msg.content}</p>
          </div>
        ))}
        {loading && (
          <div className="mr-auto text-sm text-gray-400 dark:text-gray-500 italic">
            Thinking...
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-1 text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Input */}
      <div className="border-t dark:border-gray-700 px-4 py-2">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about the sources or suggest focus areas..."
            className="flex-1 resize-none rounded-md border dark:border-gray-600
                       px-3 py-1.5 text-sm bg-white dark:bg-gray-800
                       text-gray-900 dark:text-gray-100
                       placeholder-gray-400 dark:placeholder-gray-500
                       focus:outline-none focus:ring-1 focus:ring-indigo-500"
            rows={2}
            disabled={loading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="self-end px-3 py-1.5 text-sm rounded-md
                       bg-indigo-600 text-white hover:bg-indigo-700
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            Send
          </button>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleCompile}
            disabled={compiling}
            className="mt-2 w-full px-3 py-1.5 text-sm rounded-md
                       bg-green-600 text-white hover:bg-green-700
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            {compiling ? "Queuing recompilation..." : "Recompile with guidance"}
          </button>
        )}
      </div>
    </div>
  );
}
