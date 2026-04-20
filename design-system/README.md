# WikiMind Design System

> *You never write the wiki. You feed it. Every question makes it smarter.*

WikiMind is a personal LLM-powered knowledge OS. You feed it articles, PDFs, YouTube videos, podcasts, and papers — it compiles them into a structured wiki and answers questions with full source attribution. **The wiki is the product**, not a retrieval layer.

This folder contains the visual language, type, color, components, and UI kit needed to design for WikiMind — matching the existing React + Tailwind codebase at `apps/web/`.

---

## Product context

- **Not** a note-taking app — you never write
- **Not** a chatbot — it builds something persistent
- **Not** a RAG tool — the wiki *is* the output

The product has five primary views (reflected in the sidebar):

| View | Purpose |
|---|---|
| **Inbox** | Drop sources (URL / PDF / YouTube / RSS / text). See compile status live over WebSocket. |
| **Ask** | Natural-language Q&A with conversation threads, citation chips, and "file this answer back to the wiki". |
| **Wiki** | Clean reader with concept tree (left) and backlink panel (right). Inline confidence badges on claims. |
| **Graph** | Force-directed knowledge graph — nodes=articles, edges=backlinks. |
| **Health** | Lint report: contradictions, orphans, coverage gaps, staleness. |
| **Settings** | LLM providers, cost dashboard, sync status. |

There's also a **Login** screen (dark) for the optional multi-user OAuth mode.

## Surfaces

There is **one product surface**: the WikiMind web app (React + Vite, served by a FastAPI gateway and/or an Electron desktop shell that loads the same bundle). The design system therefore ships a single UI kit: `ui_kits/app/`.

## Sources used to build this system

- **Codebase**: mounted as `wikimind/` — real React components under `apps/web/src/components/` and the Tailwind theme at `apps/web/tailwind.config.js`.
- **GitHub repo**: [`manavgup/wikimind`](https://github.com/manavgup/wikimind) — mirror of the same codebase.
- **Vision doc**: `wikimind/docs/VISION.md` — product narrative, one-liners, tone.
- **Product README**: `wikimind/README.md` — tech stack and copywriting sample.

---

## Content fundamentals

WikiMind's voice is **confident, spare, declarative**, with the posture of an editor rather than a salesperson. The product makes strong claims about what it is *not* before it tells you what it is — this pattern repeats everywhere.

### Tone
- **Declarative over promotional.** *"You never write the wiki. You feed it."* No "revolutionary", no "AI-powered" (even though it is).
- **Oppositional framing.** Copy works by negation: "Not a note-taking app · Not a chatbot · Not a RAG tool". Three-beat negations are a signature move.
- **Scholarly, not startup-y.** "Synthesis", "compile", "claims", "provenance", "lint". Words from academia and compilers, not marketing.
- **Short sentences. Often fragments.** *"None of it compounds."* stands as a full paragraph in the vision doc.
- **Second person, direct.** "*You* feed it." "*You* never write." Never "users".

### Casing
- **Sentence case** for all UI labels, headings, buttons, menu items. Never Title Case in UI chrome.
- **Lowercase** for technical nouns (`wiki`, `graph`, `lint`) even when they start sentences in a navigational label.
- **Uppercase** only for eyebrow labels and metadata: `Q1`, `SOURCES:`, `RELATED:`.

### Vocabulary — the WikiMind dictionary
These are load-bearing terms; don't substitute synonyms.

| Term | Use for |
|---|---|
| **Feed** / **Ingest** | Adding a source. Never "upload" or "import". |
| **Compile** | The LLM turning a source into a wiki article. |
| **File back** | Saving a Q&A answer as a new wiki article. |
| **Claim** | A unit of knowledge with a source. |
| **Confidence** | Every claim is *sourced / mixed / inferred / opinion*. |
| **Source** | The original material (URL, PDF, video). |
| **Article** | A compiled wiki page. |
| **Concept** | A cluster / tag across articles. |
| **Backlink** | What links to this article. |
| **Lint** / **Health** | Running the wiki quality checks. |
| **Orphan** | An article with no backlinks. |
| **Thread** / **Turn** | A Q&A conversation and its individual Q+A pairs (Q1, Q2…). |

### Emoji
- **Used sparingly as nav affordance only.** The sidebar has six emoji — 📥 💬 📚 🕸️ 🩺 ⚙️ — one per view. The brand logo is 🧠. These are fixed; don't invent new emoji elsewhere.
- **Never in body copy, headings, marketing, or buttons.**

### Example copy, drawn from the product
- `"Drop PDF here, or browse"` — quick-add bar (lowercase, instructional)
- `"All ingested sources. Live progress streams over WebSocket (connected)."` — inbox subtitle (technical, honest about its plumbing)
- `"This creates a new branch"` — fork helper text (terse, explains the effect not the control)
- `"Q1 · Q2 · Q3"` — turn labels, uppercased, period-separated
- `"Synthesized from"` — frontmatter label for concept pages
- `"Linter 83%"` — badge copy (flat number, no fanfare)

### Things we don't do
- No exclamation marks. No "!"
- No emoji in headlines or buttons. Ever.
- No marketing superlatives ("powerful", "revolutionary", "AI-driven")
- No Title Case
- No "users" — say "you"
- No em-dashes for drama inside product copy (em-dashes *are* fine in docs and marketing like this README)

---

## Visual foundations

### Palette
The product's palette is **slate neutrals + a single desaturated brand blue**. The brand blue is muted and ink-like — more "reference book" than "tech startup". See `tailwind.config.js` for the brand scale (50→900).

- **Brand blue** (`#4673ad` at 500, `#2b4876` at 700) — used for primary buttons, active nav, links, brand chips, and citation chips in Wiki Explorer.
- **Slate** everywhere else — text, borders, cards, backgrounds.
- **Sky, emerald, amber, rose** — semantic tones for the **confidence system**: sourced (emerald) · mixed (sky) · inferred (amber) · opinion (neutral slate) — and matching toast/alert colors.
- **Purple** — reserved for *fork counts* on conversation turns. Single-use accent, keep it that way.
- **Zinc/dark** — only on the Login screen.

No gradients. No colored glass. No duotone imagery.

### Type
- **Inter** for everything — UI, body, headings. Already set in `apps/web/src/index.css`.
- **JetBrains Mono** for code and for the `mono font-mono` paths that Tailwind's default would otherwise render as `ui-monospace`.
- **Instrument Serif** is *offered* in `colors_and_type.css` but used sparingly — only editorial flourishes (e.g. pull-quotes on marketing cards). The product itself is 100% sans.

Scale: 12 / 13 / 14 (default) / 16 (wiki body) / 18 / 20 / 24 / 30 (article H1) / 36.

Eyebrow labels (`Q1`, `SOURCES:`, `RELATED:`) are 12px, uppercase, `+0.04em` tracking, `slate-400`.

### Backgrounds
- Main canvas: `slate-50` (`#f8fafc`). Cards and sidebar sit on pure white on top.
- No full-bleed images. No patterns. No illustrations. No textures.
- Brand-tinted callouts use `brand-50` with `brand-100` border — reserved for the "Synthesized from" block on concept pages and active nav items.

### Borders & shadows
- **Every panel has a 1px border in `slate-200`.** This is the load-bearing visual signal — not shadow.
- Shadows are restrained: `shadow-sm` on cards (barely visible), nothing heavier until modals.
- No inner shadows. No colored shadows.

### Corner radii
- `6px` buttons and inputs (`rounded-md`)
- `8px` cards and panels (`rounded-lg`)
- `4px` inline elements (`rounded`)
- `9999px` capsule badges — citation chips, confidence badges, status pills

### Hover & press
- Hover on interactive cards: border goes `slate-200` → `brand-300`; shadow `sm` → `md`.
- Hover on nav items / rows: background fades in to `slate-100` or `brand-50` (for active).
- Buttons: `brand-600` → `brand-700` on hover (go darker). No scale transforms, no shadow bloom.
- Press state is implicit (browser default) — we don't add bespoke active states.

### Animation
- **Minimal.** Fades and color transitions only, `180ms` standard ease.
- The Spinner is the only continuous animation (border-top on a circle, CSS `animate-spin`).
- **No bouncy springs, no page transitions, no Framer Motion.**
- The Graph view is force-directed physics — that's the one exception and it's domain, not decoration.

### Transparency & blur
- **Never.** No backdrop-blur. No glass. No alpha on backgrounds. Everything is flat and opaque.

### Cards
A WikiMind card is:
```
rounded-lg · border border-slate-200 · bg-white · shadow-sm
hover:border-brand-300 hover:shadow (when interactive)
```
No colored left borders. No ribbons. No hero images.

### Imagery
The product itself ships **no marketing imagery**. In-article images (extracted from PDFs / web pages) are shown **as-is** inside a `<figure>` with a 1px `slate-200` border and an optional `slate-500` caption — no crops, no filters, no duotone.

### Layout rules
- Two- or three-column layouts, **everything separated by 1px rules, never by whitespace alone**.
- Sidebar is a fixed 224px (14rem). Wiki has a 240px concept tree left, 240px backlink rail right.
- Reader max width 720px (`max-w-3xl`) for comfortable line-length on dense markdown.

---

## Iconography

**WikiMind uses three distinct icon sources, each for a specific purpose — do not mix them.**

### 1. Emoji (fixed set, nav only)
The sidebar is the only place emoji appear. The set is **fixed**: 🧠 (brand) · 📥 Inbox · 💬 Ask · 📚 Wiki · 🕸️ Graph · 🩺 Health · ⚙️ Settings. Plus 📄 for "drop PDF here" and ✕ for dismiss. **Don't introduce new emoji.**

### 2. Inline SVG (hand-written, for domain affordances)
Two product-specific glyphs are embedded directly in component code (see `TurnCard.tsx`):
- **Fork/branch glyph** — three dots + curve, for fork counts on Q turns.
- **Pencil/edit glyph** — standard edit pen on hover for Q-editing.

These are copied verbatim into `assets/icons/` as SVG files.

### 3. Lucide (CDN, for new icons)
The codebase has no general icon font. For any new icons (close, search, chevron, external-link, etc.) use **[Lucide](https://lucide.dev)** via CDN (`https://cdn.jsdelivr.net/npm/lucide-static`). It matches the existing stroke feel of the inline SVGs (1.5–2px stroke, rounded joins) better than Heroicons or Tabler.

> **Substitution flag:** the codebase doesn't ship its own icon set, so Lucide is a closest-match substitute for future expansion. If the product adds its own, swap this out.

Rules:
- Icons are **16×16** inside buttons, **14×14** inline with text, **20×20** in empty states.
- Color inherits `currentColor` — never hard-code. An icon in a button uses the button's text color.
- **No decorative icons.** If an icon isn't load-bearing (a file-type badge, a status), don't use one.

---

## File index

| Path | What it is |
|---|---|
| `colors_and_type.css` | CSS variables for colors, type scale, spacing, radii, shadows, motion. |
| `fonts/` | (Google Fonts CDN; no local `.ttf` files shipped) |
| `assets/icons/` | Hand-written SVG glyphs extracted from the codebase (fork, edit). |
| `assets/logos/` | The brand mark (🧠 emoji + wordmark treatment) rendered as SVG + HTML reference. |
| `preview/` | The design-system cards rendered in the Design System tab. One concept per card. |
| `ui_kits/app/` | WikiMind web app UI kit. `index.html` is a click-through prototype across Inbox → Ask → Wiki. |
| `SKILL.md` | Entry point when this is used as a Claude Code skill. |
| `README.md` | You are here. |

## How to use this system

1. **Copy `colors_and_type.css`** into any new artifact and reference `var(--brand-600)`, `var(--fg-2)`, etc.
2. **Match the five rules**: 1px slate borders · slate-50 canvas · sentence case · emoji only in the nav set · Inter everywhere.
3. **Use the confidence system** when showing any LLM-produced claim — it's the product's signature pattern.
4. **Reach for `ui_kits/app/`** before designing anything new. The components there are the real visual vocabulary.
