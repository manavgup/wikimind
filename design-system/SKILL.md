---
name: wikimind-design
description: Use when designing any surface of WikiMind — the personal LLM-powered knowledge OS where the wiki is the product. Covers the visual language, tone rules, and component vocabulary for the React web app at apps/web/.
---

# WikiMind design skill

When the user asks for a WikiMind screen, flow, slide, landing page, or any artifact in the brand, load this design system before drawing anything.

## Load order

1. **Read `README.md`** — the full visual + content system. Do not skip.
2. **Copy `colors_and_type.css` into your artifact.** Use `var(--brand-600)`, `var(--fg-2)`, etc. Never re-invent the palette.
3. **Open `ui_kits/app/index.html` in a tab** (or copy the relevant `.jsx` file) and lift components verbatim. The Inbox, Ask, and Wiki views are fully mocked with real data shapes.
4. **Browse `preview/`** for any single-concept reference (colors, type, buttons, badges, chips, nav, source card, turn card, toast).

## The five non-negotiables

If a design violates any of these, it's not WikiMind:

1. **1px slate-200 borders separate everything.** Borders carry the layout, not shadow or whitespace.
2. **`slate-50` canvas + pure white cards.** No gradients, no tints, no imagery, no glass.
3. **Sentence case in all UI.** No Title Case. No marketing caps.
4. **Emoji are nav-only and fixed.** 🧠 📥 💬 📚 🕸️ 🩺 ⚙️ — and 📄 ✕. Do not invent new ones.
5. **Inter everywhere.** JetBrains Mono only for code.

## Voice cheat-sheet

- Declarative, spare, scholarly. "You feed it. You never write it."
- Oppositional framing in three beats. "Not a note app · Not a chatbot · Not a RAG tool."
- Use the dictionary: feed, compile, claim, confidence, file back, source, article, concept, backlink, orphan, lint, thread, turn.
- No exclamation marks. No "users" (say "you"). No "AI-powered" / "revolutionary".

## The confidence system is the signature pattern

Every LLM-produced claim gets tagged: **sourced** (emerald) · **mixed** (sky) · **inferred** (amber) · **opinion** (slate). If you're designing anything that surfaces a generated claim and you don't show confidence, you're off-brand.

## When making slides, landing, or marketing

- Keep the visual rules (1px borders, slate canvas, no imagery) — marketing is just product cards arranged with more air.
- `Instrument Serif` italic is allowed for a single editorial pull-quote per page. Nowhere else.
- Background color variety is OK: brand-50 tint, slate-900 inverted section. Still no gradients.

## When designing new product screens

- Start from `ui_kits/app/` and extend. Don't mock from scratch.
- Sidebar nav is fixed 224px. Wiki view has 240px concept tree left + 240px backlink rail right. Reader max-width 720px.
- New icons → Lucide via CDN, `currentColor`, 16/14/20 px depending on context.
