# ADR-004: Plain markdown files + SQLite metadata

## Status

Accepted

## Context

WikiMind produces wiki articles from ingested sources. We need to decide where
and how article content is stored. The storage choice affects portability,
version control friendliness, human readability, backup simplicity, and the
ability to use external tools (editors, grep, git) on the knowledge base.

The product vision emphasizes: "your knowledge is yours" -- no lock-in, export
everything as plain text, human-readable, and git-friendly.

## Decision

Article content is stored as **plain markdown files** in the filesystem at
`~/.wikimind/wiki/{concept}/{slug}.md`. Structured metadata (source records,
article records, concepts, backlinks, jobs, cost logs) is stored in **SQLite**
(see ADR-001).

Each `.md` file includes YAML frontmatter with machine-readable metadata
(title, slug, source URL, source type, compilation timestamp, concepts,
confidence level). The article body contains summary, key claims, analysis,
open questions, related links, and sources.

The filesystem layout is:
```
~/.wikimind/wiki/
  index.md
  {concept}/
    {slug}.md
  _meta/
    backlinks.json
    concepts.json
    health.json
```

SQLite stores the relationships and queryable fields (Article table with slug,
title, file_path, concept_ids, confidence, linter_score, summary, source_ids).
The `.md` file is the source of truth for content; the database is the source
of truth for relationships and search indexes.

## Alternatives Considered

**All-in-database** -- Store article content as TEXT columns in SQLite. Simpler
architecture but loses human readability, git-friendliness, and the ability to
edit articles with any text editor. Users could not `grep` their knowledge base
or diff changes over time.

**Obsidian vault format** -- Use Obsidian's `[[wikilink]]` convention. We
actually do use `[[backlink]]` syntax in the Related section, but we chose not
to couple the entire storage format to Obsidian. Our frontmatter schema is
richer (confidence levels, source attribution) and we need SQLite for query
performance.

**JSON files** -- Machine-readable but not human-readable. Defeats the purpose
of a wiki that users can browse with any tool.

**CMS/database-only (Notion-style)** -- Proprietary storage that locks users
in. Explicitly rejected by the product vision.

## Consequences

**Enables:**
- Users can browse, edit, and search their wiki with any text editor or CLI tool
- `git init` in `~/.wikimind/wiki/` gives full version history for free
- Backup is a directory copy; migration is a file copy
- Content survives even if WikiMind is uninstalled -- it is just markdown files
- External tools (Obsidian, VS Code, grep) work out of the box

**Constrains:**
- Full-text search requires either reading files from disk or maintaining a
  separate search index (ChromaDB embeddings planned)
- Renames/moves must update both the file and the database record
- Two sources of truth (files + database) can drift; the linter detects this

**Risks:**
- Filesystem operations are not transactional with database writes; a crash
  mid-save could leave the file written but the database not updated (or vice
  versa). Mitigated by writing the file first, then committing the database
  record.
