# WikiMind
### Personal LLM Knowledge OS — Product Specification

---

## The One-Line Pitch

> You never write the wiki. You feed it. Every question makes it smarter.

---

## The Problem

Knowledge workers consume hundreds of articles, papers, podcasts, and videos weekly. They highlight. They bookmark. They save to Notion.

**None of it compounds.**

Every insight lives in isolation. Every new project means starting over from memory. The synthesis never happens because *synthesis is expensive* — it requires time, focus, and the ability to hold many things in your head at once.

LLMs can do exactly that. But nobody has built the right loop.

---

## The Core Loop

```
Feed → Compile → Query → Answer files back → Wiki gets smarter → Repeat
```

This is fundamentally different from every existing tool:
- **Notion/Obsidian:** You write everything manually
- **NotebookLM:** Single session, no persistence
- **Perplexity:** Answers questions, builds nothing
- **RAG tools:** Technical, no living wiki abstraction
- **mem.ai:** Captures fragments, never synthesizes

WikiMind is the **first tool where the knowledge base itself is the product** — and the LLM builds and maintains it.

---

## Target User

**Primary persona:** The High-Consumption Expert

- Researchers, CTOs, investors, consultants, analysts, architects
- Reads 50–100 articles/week across 3–5 deep domains
- Has strong opinions, builds frameworks, publishes content
- Frustrated that their knowledge doesn't accumulate into anything reusable
- Values ownership and portability of their own thinking

**This is not a general note-taking app.** It's for people whose *knowledge is their product*.

---

## Core Architecture

### Three Layers

```
┌─────────────────────────────────────────┐
│           INGEST LAYER                  │
│  Web · PDF · Audio · Video · Text · API │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│           LLM ENGINE                    │
│  Compiler · Q&A Agent · Linter · Index  │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│           KNOWLEDGE STORE               │
│  Wiki · Graph · Facts · Confidence Map  │
└─────────────────────────────────────────┘
```

---

## Ingest Layer — Source Types

Everything a knowledge worker actually consumes:

| Source | Method |
|---|---|
| Web articles / blogs | Browser extension (one-click clip) |
| PDFs / papers | Drag and drop |
| YouTube videos | URL → auto-transcribe |
| Podcasts / audio | URL or upload → transcribe |
| Tweets / threads | URL capture |
| Newsletters | Email forwarding address |
| Raw text / notes | Paste or quick-capture hotkey |
| RSS feeds | Auto-ingest on schedule |
| Existing Notion/Obsidian | One-time import |

**Design principle:** Zero friction on ingest. Capture now, compile later. The inbox is a holding zone — nothing is lost, nothing requires immediate action.

---

## LLM Engine — Four Components

### 1. Compiler
Transforms raw sources into structured wiki articles.

For each source it produces:
- Article title and 2-sentence summary
- Key claims (bulleted, attributed to source)
- Concepts extracted and tagged
- Backlinks to related existing wiki articles
- Confidence classification: *sourced fact / author opinion / LLM inference*

Runs automatically on ingest, or on-demand batch.

### 2. Q&A Agent
Answers natural language questions against the full wiki.

Every answer includes:
- Direct response with inline source attribution
- Related wiki articles surface automatically
- Option to **file the answer back** as a new wiki article
- Suggested follow-up questions based on gaps detected

This is the compounding flywheel. Every question enriches the wiki.

### 3. Linter / Healer
Runs periodically in the background. Finds:
- Contradicting claims across articles
- Orphaned articles (no connections to anything)
- Coverage gaps in a topic cluster
- Stale articles whose sources have been superseded
- Missing articles implied by backlinks that don't exist yet

Produces a **Wiki Health Report** — actionable, not overwhelming.

### 4. Indexer
Maintains the connective tissue automatically:
- Concept taxonomy (auto-generated, user-adjustable)
- Backlink map across all articles
- Topic cluster detection
- Confidence-weighted knowledge graph

---

## Knowledge Store — What Gets Built

### Wiki Articles
Plain structured text. Human-readable. Exportable. Not locked in any proprietary format.

Each article has:
- Title, summary, last updated
- Body: key claims, analysis, open questions
- Backlinks: incoming and outgoing
- Source trail: every claim attributed
- Confidence layer: what's sourced vs. inferred

### Knowledge Graph
Visual force-directed graph of your entire knowledge base.

- Nodes = concepts and articles
- Edges = backlinks and semantic relationships
- Cluster view by topic domain
- Click any node → open article
- See your knowledge *as a structure*, not a list

### Structured Facts Store
Extracted entities, claims, and relationships in queryable form:
- "What do I know about [topic]?"
- "What sources support [claim]?"
- "Where do my notes contradict each other?"

---

## User Interface — Five Views

### 1. Inbox
- All raw sources, unprocessed and processing
- Compilation status indicators
- Quick-add bar always visible
- Batch compile button

### 2. Wiki Explorer
- Clean reading interface
- Left panel: topic tree / concept taxonomy
- Right panel: backlinks and related articles
- Inline confidence badges on claims
- Full-text search across wiki + raw simultaneously

### 3. Ask
- Natural language query bar
- Answer with sources, confidence, related articles
- "Save this answer to wiki" toggle
- Conversation history persists per topic thread

### 4. Graph
- Force-directed knowledge graph
- Filter by topic, date range, source type, confidence
- Orphan detector overlay
- Gap highlighter (thin clusters = weak knowledge)

### 5. Health Dashboard
- Wiki coverage score by domain
- Contradiction alerts
- Staleness warnings
- Suggested new articles to create
- Source diversity metrics (are you in an echo chamber?)

---

## Output Layer

The wiki is also a *publishing tool*:

| Output | Format |
|---|---|
| Article export | PDF, clean HTML |
| Slide deck | Auto-generated from any topic cluster |
| Newsletter draft | Prose summary of recent wiki additions |
| LinkedIn post | Key insight + supporting claims formatted for social |
| Summary report | "What I know about X" as a shareable document |
| Public wiki | Toggle any topic cluster to a public URL |

---

## Privacy & Data Model

**Core principle: your knowledge is yours.**

- All wiki data stored locally first, cloud sync optional
- LLM calls are ephemeral — source content is not used for training
- Self-hosted option for sensitive domains (legal, medical, enterprise)
- Export everything, anytime, as plain text — no lock-in
- Bring your own API key option (Anthropic, OpenAI, local models via Ollama)

This is a significant differentiator vs. cloud-native tools for professionals in regulated fields.

---

## What WikiMind Is Not

- Not a search engine (Perplexity)
- Not a document editor (Notion)
- Not a chat interface (ChatGPT)
- Not a bookmark manager (Raindrop)
- Not a flashcard tool (Anki)

It is the **knowledge synthesis layer** that sits above all of these — and can ingest from all of them.

---

## Monetization

| Tier | Price | What's included |
|---|---|---|
| **Free** | $0 | 200 wiki articles, 3 source types, basic Q&A |
| **Pro** | $20/month | Unlimited articles, all ingest types, health dashboard, all outputs |
| **Scholar** | $40/month | Pro + multiple knowledge bases, advanced graph, collaboration (share read-only wikis) |
| **Enterprise** | Custom | Private deployment, SSO, audit trails, custom LLM routing, on-prem |

---

## MVP Scope — What to Build First

**Four things, nothing else:**

1. **Ingest:** Web clipper extension + PDF upload + paste text
2. **Compiler:** Single Claude API call per source → structured `.md` article with backlinks
3. **Wiki Explorer:** Clean reader with backlink sidebar and full-text search
4. **Ask:** Q&A against wiki with "save answer" option

**Success metric for MVP:** A user feeds 20 sources in one sitting, asks 5 questions, and says *"this knows more about my topic than my notes do."*
