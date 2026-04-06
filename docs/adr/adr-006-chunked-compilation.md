# ADR-006: Chunked compilation for large documents

## Status

Accepted

## Context

WikiMind ingests sources of widely varying sizes: a short blog post may be 2K
tokens, while a research paper or long-form transcript can exceed 100K tokens.
LLM context windows have practical limits -- even models with 200K token windows
produce lower-quality output when the input is very long. We also need to control
cost: a single 100K-token compilation at Claude Sonnet rates costs roughly $0.30
in input tokens alone.

We need a strategy for handling documents that exceed a reasonable single-call
threshold while maintaining coherence in the final compiled article.

## Decision

The `Compiler` class splits documents at **80,000 estimated tokens** into chunks
and compiles each chunk independently, then merges the results.

The chunking strategy (`chunk_text` in `ingest/service.py`) splits on markdown
headings (`#`, `##`, `###`) to preserve semantic boundaries, with a fallback to
splitting at 4,000-token intervals. Each `DocumentChunk` retains its heading
path (e.g., `["Introduction", "Key Claims"]`) for context.

The merge strategy (`_merge_chunk_results`) combines results by:
- Concatenating all key claims (capped at 20)
- Unioning concepts and backlink suggestions (capped at 10 each)
- Deduplicating open questions (capped at 5)
- Joining article bodies with horizontal rules
- Using the first chunk's summary as the article summary

A maximum of 10 chunks are compiled per document to bound cost and latency.

## Alternatives Considered

**Map-reduce with a synthesis pass** -- Compile chunks independently, then run
a final LLM call to synthesize a unified article. Produces more coherent output
but doubles the LLM cost and adds latency. We plan to add this as an optional
"deep compile" mode in the future.

**Truncation** -- Simply cut the document at 80K tokens and compile what fits.
Loses information from the rest of the document, which is unacceptable for
research papers where key findings often appear in later sections.

**Sliding window with overlap** -- Overlap chunks by 500 tokens to preserve
context across boundaries. Adds complexity and increases total tokens sent.
The heading-based splitting already preserves semantic context well enough.

**RAG-only (no full compilation)** -- Embed chunks and retrieve relevant ones
at query time instead of compiling upfront. Loses the "living wiki" value
proposition -- users want articles they can read, not just a retrieval system.

## Consequences

**Enables:**
- Documents of any length can be compiled without hitting context limits
- Cost is predictable: roughly proportional to document length
- Heading-aware chunking preserves the document's logical structure
- The 10-chunk cap prevents runaway costs on extremely large documents

**Constrains:**
- Merged articles may have some redundancy across chunk boundaries
- The first chunk's summary may not represent the full document well
- Cross-chunk references (e.g., "as mentioned in Section 3") are lost

**Risks:**
- 80K token threshold is a heuristic; some models could handle more. This
  should be configurable per provider in the future.
- Heading-based splitting may produce very uneven chunks if the document has
  few headings. The 4K-token fallback mitigates this.
