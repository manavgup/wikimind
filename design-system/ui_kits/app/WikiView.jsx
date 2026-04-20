/* global React */
const { useState, useMemo } = React;

const CONCEPTS = [
  { name: "Systems & distributed", slug: "systems", children: [
    { name: "Consensus", slug: "consensus", count: 4 },
    { name: "Databases", slug: "databases", count: 7 },
    { name: "Storage engines", slug: "storage", count: 3 },
  ]},
  { name: "Programming languages", slug: "languages", children: [
    { name: "Rust", slug: "rust", count: 6 },
    { name: "Type theory", slug: "type-theory", count: 2 },
  ]},
  { name: "ML & LLMs", slug: "ml", children: [
    { name: "Transformers", slug: "transformers", count: 5 },
    { name: "Retrieval", slug: "retrieval", count: 3 },
    { name: "Evaluation", slug: "evaluation", count: 2 },
  ]},
];

const ARTICLES = [
  { slug: "borrow-checker", title: "Borrow checker", summary: "How Rust's type system statically rules out data races via aliasing-xor-mutability.", confidence: "sourced", concept: "rust", linter: 0.91, pageType: "article", concepts: ["rust", "concurrency"] },
  { slug: "raft", title: "Raft consensus", summary: "Leader-based consensus algorithm. Strong guarantees, simpler to implement than Paxos.", confidence: "mixed", concept: "consensus", linter: 0.83, pageType: "article", concepts: ["consensus", "systems"] },
  { slug: "attention-is-all-you-need", title: "Attention Is All You Need", summary: "The 2017 paper that introduced the Transformer architecture — no recurrence, just self-attention.", confidence: "sourced", concept: "transformers", linter: 0.88, pageType: "article", concepts: ["transformers", "ml"] },
  { slug: "lsm-trees", title: "LSM-trees", summary: "Write-optimized storage engines using in-memory buffers and periodic compaction.", confidence: "sourced", concept: "storage", linter: 0.79, pageType: "article", concepts: ["storage", "databases"] },
  { slug: "send-sync", title: "Send and Sync", summary: "The two marker traits that make Rust's concurrency story sound.", confidence: "sourced", concept: "rust", linter: 0.94, pageType: "article", concepts: ["rust", "concurrency"] },
  { slug: "vector-search", title: "Vector search", summary: "ANN indexes — HNSW, IVF, product quantization — trade recall for latency.", confidence: "mixed", concept: "retrieval", linter: 0.71, pageType: "article", concepts: ["retrieval", "ml"] },
  { slug: "concurrency", title: "Concurrency", summary: "Concept page synthesizing what you know about concurrent programming.", confidence: "mixed", concept: "rust", linter: 0.72, pageType: "concept", concepts: ["concurrency"], synthesizedFrom: ["borrow-checker", "send-sync", "raft"] },
];

const BACKLINKS_BY_SLUG = {
  "borrow-checker": ["Send and Sync", "Concurrency", "Rust ownership model"],
  "raft": ["Consensus", "Leader election", "Designing Data-Intensive Applications"],
  "attention-is-all-you-need": ["Self-attention", "Transformer", "Positional encoding"],
  "lsm-trees": ["RocksDB", "SSTable", "Write amplification"],
  "send-sync": ["Borrow checker", "Concurrency", "Arc and Mutex"],
  "vector-search": ["HNSW", "Embeddings", "Retrieval"],
  "concurrency": ["Borrow checker", "Send and Sync", "Raft"],
};

function ConceptTree({ activeConcept, onSelect }) {
  return (
    <nav className="p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Concepts</div>
      <button type="button" onClick={() => onSelect(null)}
        className={`mb-2 block w-full rounded-md px-2 py-1 text-left text-sm transition ${
          !activeConcept ? "bg-brand-50 text-brand-700 font-medium" : "text-slate-600 hover:bg-slate-100"
        }`}>All articles</button>
      {CONCEPTS.map((group) => (
        <div key={group.slug} className="mb-3">
          <div className="px-2 py-1 text-xs font-semibold text-slate-500">{group.name}</div>
          {group.children.map((c) => (
            <button key={c.slug} type="button" onClick={() => onSelect(c.slug)}
              className={`flex w-full items-center justify-between rounded-md px-3 py-1 text-sm transition ${
                activeConcept === c.slug ? "bg-brand-50 text-brand-700 font-medium" : "text-slate-600 hover:bg-slate-100"
              }`}>
              <span>{c.name}</span>
              <span className="text-xs text-slate-400">{c.count}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

function SearchBar() {
  return (
    <input type="search" placeholder="Search wiki + raw sources..."
      className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
  );
}

function PageTypeIndicator({ pageType }) {
  if (pageType === "concept")
    return <Badge tone="brand">Concept</Badge>;
  return <Badge tone="neutral">Article</Badge>;
}

function ArticleCard({ article, onOpen }) {
  return (
    <Card className="p-4" onClick={() => onOpen(article.slug)}>
      <div className="flex items-center gap-2">
        <PageTypeIndicator pageType={article.pageType} />
        <ConfidenceBadge level={article.confidence} />
      </div>
      <h3 className="mt-2 text-base font-semibold text-slate-900">{article.title}</h3>
      <p className="mt-1 text-sm text-slate-600">{article.summary}</p>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
        <span>Linter {Math.round(article.linter * 100)}%</span>
        <span>·</span>
        <span>{article.concepts.join(" · ")}</span>
      </div>
    </Card>
  );
}

function ArticleGrid({ activeConcept, onOpen }) {
  const filtered = useMemo(
    () => activeConcept ? ARTICLES.filter(a => a.concepts.includes(activeConcept) || a.concept === activeConcept) : ARTICLES,
    [activeConcept]
  );
  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-xl font-semibold text-slate-900">
          {activeConcept ? activeConcept.replace("-", " ") : "All articles"}
        </h2>
        <span className="text-sm text-slate-500">{filtered.length} article{filtered.length === 1 ? "" : "s"}</span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {filtered.map((a) => <ArticleCard key={a.slug} article={a} onOpen={onOpen} />)}
      </div>
    </div>
  );
}

function ArticleReader({ article, onOpen }) {
  const backlinks = BACKLINKS_BY_SLUG[article.slug] ?? [];
  return (
    <article className="mx-auto max-w-3xl p-8">
      <header className="mb-6 border-b border-slate-200 pb-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <PageTypeIndicator pageType={article.pageType} />
          <ConfidenceBadge level={article.confidence} />
          <Badge tone="info">Linter {Math.round(article.linter * 100)}%</Badge>
          {article.concepts.map((c) => <Badge key={c} tone="brand">{c}</Badge>)}
        </div>
        <h1 className="text-3xl font-bold text-slate-900 tracking-tight">{article.title}</h1>
        <p className="mt-2 text-base text-slate-600">{article.summary}</p>

        {article.pageType === "concept" && article.synthesizedFrom && (
          <div className="mt-3 rounded-md border border-brand-100 bg-brand-50 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-brand-700">Synthesized from</p>
            <ul className="flex flex-wrap gap-2">
              {article.synthesizedFrom.map((slug) => (
                <li key={slug}>
                  <button onClick={() => onOpen(slug)} className="inline-block rounded-md border border-brand-200 bg-white px-2 py-0.5 text-xs text-brand-700 hover:bg-brand-50">
                    {slug}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </header>

      <div className="prose prose-slate max-w-none text-slate-700 [&_p]:text-base [&_p]:leading-relaxed">
        <p>
          The <strong>borrow checker</strong> is the static analysis pass in the Rust compiler that enforces the language's two most important invariants: <em>values have exactly one owner</em>, and <em>references follow aliasing XOR mutability</em>.
          <ConfidenceBadgeInline level="sourced" />
        </p>
        <h2 className="mt-6 text-xl font-semibold text-slate-900">Why it exists</h2>
        <p>
          Data races are the single largest source of concurrency bugs in systems languages. They require a very specific condition: two threads touching the same memory, at least one of them writing, with no synchronisation. Every other major memory safety bug — use-after-free, iterator invalidation, double-free — stems from the same underlying cause: <em>shared mutable state</em>.
          <ConfidenceBadgeInline level="sourced" />
        </p>
        <p>
          Rust's insight was that you can eliminate the entire class by restricting the type system. If the compiler can <em>prove</em> that no two references to the same data exist when one of them is mutable, the races become unconstructable. The cost is that some valid programs (those that would never actually race at runtime) are rejected — Rust calls this "fighting the borrow checker".
          <ConfidenceBadgeInline level="inferred" />
        </p>
        <h2 className="mt-6 text-xl font-semibold text-slate-900">How it interacts with concurrency</h2>
        <p>
          The <a href="#" onClick={(e) => { e.preventDefault(); onOpen("send-sync"); }} className="text-brand-700 underline decoration-dotted underline-offset-2 hover:text-brand-900">Send and Sync</a> traits extend the rule across thread boundaries. A <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">&mut T</code> is <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">Send</code> but not <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">Sync</code> — so it can move between threads, but the type system prevents two threads from holding it at once.
          <ConfidenceBadgeInline level="sourced" />
        </p>
        <p>
          In practice this means you reach for <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">Arc&lt;Mutex&lt;T&gt;&gt;</code> when you need shared mutable state across threads: <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">Arc</code> for the shared ownership, <code className="rounded bg-slate-100 px-1 py-0.5 text-[13px]">Mutex</code> to turn <em>aliased</em> access into <em>exclusive</em> access on demand.
          <ConfidenceBadgeInline level="mixed" />
        </p>
      </div>

      <aside className="mt-10 rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Backlinks</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {backlinks.map((name) => (
            <span key={name} className="cursor-pointer rounded-full bg-white border border-slate-200 px-3 py-1 text-xs font-medium text-slate-700 hover:border-brand-300 hover:text-brand-700">
              {name}
            </span>
          ))}
        </div>
      </aside>
    </article>
  );
}

function ConfidenceBadgeInline({ level }) {
  return <span className="ml-1 inline-block align-middle"><ConfidenceBadge level={level} /></span>;
}

function BacklinkPanel({ article }) {
  if (!article) return null;
  const backlinks = BACKLINKS_BY_SLUG[article.slug] ?? [];
  return (
    <div className="p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Backlinks · {backlinks.length}</div>
      <ul className="flex flex-col gap-1">
        {backlinks.map((name) => (
          <li key={name}>
            <a href="#" onClick={(e) => e.preventDefault()} className="block rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100 hover:text-brand-700">{name}</a>
          </li>
        ))}
      </ul>
      <div className="mt-6 mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Outgoing</div>
      <ul className="flex flex-col gap-1">
        <li><a href="#" onClick={(e) => e.preventDefault()} className="block rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100 hover:text-brand-700">Send and Sync</a></li>
        <li><a href="#" onClick={(e) => e.preventDefault()} className="block rounded-md px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100 hover:text-brand-700">Arc and Mutex</a></li>
        <li><a href="#" onClick={(e) => e.preventDefault()} className="block rounded-md px-2 py-1.5 text-sm text-slate-400 decoration-dotted underline underline-offset-2" title="Article not yet in wiki">Lifetime elision</a></li>
      </ul>
    </div>
  );
}

function WikiView() {
  const [activeConcept, setActiveConcept] = useState(null);
  const [openSlug, setOpenSlug] = useState(null);
  const article = openSlug ? ARTICLES.find(a => a.slug === openSlug) : null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex items-center gap-4 border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-900">Wiki</h1>
        <div className="max-w-md flex-1"><SearchBar /></div>
        {openSlug && (
          <Button variant="ghost" size="sm" onClick={() => setOpenSlug(null)}>← Back to grid</Button>
        )}
      </header>

      {article ? (
        <div className="grid flex-1 grid-cols-[15rem_1fr_15rem] overflow-hidden">
          <aside className="overflow-y-auto border-r border-slate-200 bg-white">
            <ConceptTree activeConcept={activeConcept} onSelect={(c) => { setActiveConcept(c); setOpenSlug(null); }} />
          </aside>
          <section className="overflow-y-auto bg-slate-50">
            <ArticleReader article={article} onOpen={setOpenSlug} />
          </section>
          <aside className="overflow-y-auto border-l border-slate-200 bg-white">
            <BacklinkPanel article={article} />
          </aside>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-[15rem_1fr] overflow-hidden">
          <aside className="overflow-y-auto border-r border-slate-200 bg-white">
            <ConceptTree activeConcept={activeConcept} onSelect={setActiveConcept} />
          </aside>
          <section className="overflow-y-auto bg-slate-50">
            <ArticleGrid activeConcept={activeConcept} onOpen={setOpenSlug} />
          </section>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { WikiView });
