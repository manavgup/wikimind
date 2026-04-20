/* global React */
const { useState, useRef, useEffect } = React;

const INITIAL_CONVERSATIONS = [
  {
    id: "c1",
    title: "Rust ownership & data races",
    updated: "10 min ago",
    forks: 1,
    turns: [
      {
        id: "t1", turnIndex: 0,
        question: "What's the borrow checker and why does it exist?",
        answer: "The **borrow checker** is the Rust compiler pass that enforces the language's _aliasing XOR mutability_ rule at compile time: at any given scope, a value can have either many immutable references _or_ exactly one mutable reference, but never both simultaneously.\n\nIt exists because data races — the single largest class of concurrency bugs — require exactly the condition the borrow checker forbids: a shared mutable reference accessed from multiple threads without synchronisation. By making this a type error, Rust catches data races before the program runs.",
        sources: ["Rust ownership model", "Fearless concurrency"],
        related: ["Lifetime elision", "Smart pointers"],
        confidence: "sourced",
        forks: 1,
      },
      {
        id: "t2", turnIndex: 1,
        question: "How does the borrow checker prevent data races specifically?",
        answer: "A data race requires two threads, one of them writing, to access the same location without synchronisation. In Rust, moving a value across threads requires the value to implement `Send`, and sharing a reference across threads requires `Sync`. A `&mut T` is `Send` but not `Sync` — so it can move between threads, but the type system prevents two threads from holding it at once. A plain `&T` is `Sync` but cannot co-exist with a `&mut T` to the same data. Together these rules statically rule out the shared-mutable case that causes races.",
        sources: ["Rust ownership model"],
        related: ["Send and Sync", "Arc<Mutex>"],
        confidence: "sourced",
      },
    ],
  },
  {
    id: "c2", title: "Distributed consensus at scale", updated: "Yesterday", forks: 0,
    turns: [{
      id: "t3", turnIndex: 0,
      question: "When do I actually need Raft vs a simpler leader election?",
      answer: "Raft is overkill when you only need _liveness_ under failures — e.g. picking a coordinator. You need Raft (or Paxos) when you also need _linearizable replicated state_ — every replica must agree on the exact sequence of operations, not just which node is leader.",
      sources: ["Designing Data-Intensive Applications — Ch. 9"],
      related: ["Paxos", "Byzantine fault tolerance"],
      confidence: "mixed",
    }],
  },
  { id: "c3", title: "PDF extraction — Docling vs pymupdf", updated: "3 days ago", forks: 0, turns: [] },
  { id: "c4", title: "What have I read about vector DBs?", updated: "Apr 12", forks: 2, turns: [] },
];

function TurnCard({ turn, streaming }) {
  const [expanded, setExpanded] = useState(turn.answer.length < 800);
  const answer = expanded ? turn.answer : turn.answer.slice(0, 600) + "…";

  return (
    <article className="group rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <header className="mb-3">
        <div className="flex items-center gap-2">
          <Eyebrow>Q{turn.turnIndex + 1}</Eyebrow>
          {turn.forks > 0 && (
            <span className="inline-flex items-center gap-0.5 rounded bg-purple-50 px-1.5 py-0.5 text-xs font-medium text-purple-600">
              <IconFork size={12} /> {turn.forks}
            </span>
          )}
        </div>
        <h3 className="mt-1 text-base font-semibold text-slate-900">{turn.question}</h3>
      </header>

      <div className="prose prose-sm max-w-none text-slate-700">
        {streaming ? (
          <p className="flex items-center gap-2 text-slate-500">
            <Spinner size={12} /> Thinking through the wiki…
          </p>
        ) : (
          answer.split("\n\n").map((p, i) => (
            <p key={i} dangerouslySetInnerHTML={{ __html: p.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code class='rounded bg-slate-100 px-1 py-0.5 text-[12.5px]'>$1</code>").replace(/_([^_]+)_/g, "<em>$1</em>") }} />
          ))
        )}
      </div>

      {!streaming && turn.answer.length > 800 && (
        <button type="button" onClick={() => setExpanded(v => !v)}
          className="mt-2 text-sm font-medium text-brand-600 hover:underline">
          {expanded ? "Show less" : "Show more"}
        </button>
      )}

      {!streaming && turn.sources?.length > 0 && (
        <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <Eyebrow>Sources:</Eyebrow>
          {turn.sources.map((t, i) => (
            <span key={i} className="cursor-pointer rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100">{t}</span>
          ))}
        </footer>
      )}
      {!streaming && turn.related?.length > 0 && (
        <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <Eyebrow>Related:</Eyebrow>
          {turn.related.map((t, i) => (
            <span key={i} className="cursor-pointer rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100">{t}</span>
          ))}
        </footer>
      )}
      {!streaming && turn.confidence && (
        <div className="mt-2 text-xs text-slate-400">
          Confidence: <span className="font-medium text-slate-600">{turn.confidence}</span>
        </div>
      )}
    </article>
  );
}

function ConversationHistory({ conversations, activeId, onSelect, onNew }) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 p-3">
        <Button variant="secondary" className="w-full" onClick={onNew}>+ New thread</Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {conversations.map((c) => (
          <button key={c.id} type="button" onClick={() => onSelect(c.id)}
            className={`block w-full rounded-md p-2.5 text-left transition ${
              activeId === c.id ? "bg-brand-50" : "hover:bg-slate-50"
            }`}>
            <div className={`truncate text-sm font-medium ${activeId === c.id ? "text-brand-700" : "text-slate-900"}`}>
              {c.title}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
              <span>{c.updated}</span>
              {c.forks > 0 && (
                <span className="inline-flex items-center gap-0.5 text-purple-500">
                  <IconFork size={10} /> {c.forks}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function QueryInput({ onSubmit, disabled }) {
  const [q, setQ] = useState("");
  const submit = (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    onSubmit(q.trim());
    setQ("");
  };
  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="Ask anything about what you've fed the wiki..."
        className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
      <Button type="submit" disabled={disabled || !q.trim()}>
        {disabled ? <Spinner size={12} /> : null} Ask
      </Button>
    </form>
  );
}

function AskView({ pushToast }) {
  const [conversations, setConversations] = useState(INITIAL_CONVERSATIONS);
  const [activeId, setActiveId] = useState("c1");
  const [streaming, setStreaming] = useState(false);
  const threadRef = useRef(null);

  const conversation = conversations.find(c => c.id === activeId);

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [activeId, conversation?.turns.length, streaming]);

  const handleNew = () => {
    const id = "c" + Date.now();
    setConversations((cs) => [{ id, title: "New thread", updated: "Just now", forks: 0, turns: [] }, ...cs]);
    setActiveId(id);
  };

  const handleAsk = (question) => {
    if (!conversation) return;
    setStreaming(true);
    const turnId = "t" + Date.now();
    const turnIndex = conversation.turns.length;
    // Add streaming turn
    setConversations((cs) => cs.map(c => c.id === activeId ? {
      ...c,
      title: c.turns.length === 0 ? question.slice(0, 48) : c.title,
      updated: "Just now",
      turns: [...c.turns, { id: turnId, turnIndex, question, answer: "", sources: [], related: [], confidence: null }],
    } : c));
    // Fake streaming completion
    setTimeout(() => {
      setConversations((cs) => cs.map(c => c.id === activeId ? {
        ...c,
        turns: c.turns.map(t => t.id === turnId ? {
          ...t,
          answer: "Based on what you've fed the wiki so far, **the short answer is yes** — though the details depend on which sources you trust. The citations below represent the strongest supporting articles; related links cover adjacent concepts that didn't directly answer the question but are close neighbours in the graph.",
          sources: ["Rust ownership model", "Fearless concurrency"],
          related: ["Send and Sync", "Data race"],
          confidence: "sourced",
        } : t),
      } : c));
      setStreaming(false);
    }, 1800);
  };

  const handleSave = () => {
    pushToast({ kind: "success", title: "Saved thread to wiki", detail: conversation?.title });
  };

  return (
    <div className="flex h-full">
      <aside className="w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-white">
        <ConversationHistory conversations={conversations} activeId={activeId} onSelect={setActiveId} onNew={handleNew} />
      </aside>
      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-slate-900">{conversation?.title ?? "New thread"}</h1>
            <p className="text-xs text-slate-500">{conversation?.turns.length ?? 0} turn{conversation?.turns.length === 1 ? "" : "s"}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={handleSave} disabled={!conversation?.turns.length}>File back to wiki</Button>
            <Button variant="ghost" size="sm" disabled={!conversation?.turns.length}>Export</Button>
          </div>
        </header>

        <div ref={threadRef} className="flex-1 overflow-y-auto p-6">
          {conversation?.turns.length === 0 ? (
            <div className="mx-auto mt-20 max-w-xl text-center">
              <div className="text-3xl">💬</div>
              <h2 className="mt-3 text-lg font-semibold text-slate-800">Ask the wiki</h2>
              <p className="mt-2 text-sm text-slate-500">Every answer is grounded in sources you've fed. You can file any answer back as a new wiki article.</p>
            </div>
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {conversation?.turns.map((t, i) => (
                <TurnCard key={t.id} turn={t} streaming={streaming && i === conversation.turns.length - 1 && !t.answer} />
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-slate-200 p-4">
          <div className="mx-auto max-w-3xl">
            <QueryInput onSubmit={handleAsk} disabled={streaming} />
          </div>
        </div>
      </main>
    </div>
  );
}

Object.assign(window, { AskView });
