# ADR-005: Confidence-tagged claims

## Status

Accepted

## Context

WikiMind compiles raw sources into structured wiki articles using LLMs. LLMs
can hallucinate, editorialize, and blend source material with their own
inferences. Users of a personal knowledge base need to know whether a claim
comes directly from the source, was inferred by the LLM, or represents the
original author's stated opinion.

Without confidence tagging, a wiki full of LLM-compiled articles becomes an
unreliable mix of facts and inferences with no way to distinguish between them.

## Decision

Every claim extracted during compilation receives a **confidence classification**
from the `ConfidenceLevel` enum:

- **sourced** -- Claim directly attributable to the source material, optionally
  with a short verbatim quote (under 15 words)
- **mixed** -- Combination of source material and LLM inference
- **inferred** -- LLM synthesis not directly stated in the source
- **opinion** -- The original author's stated opinion, not a factual claim

The compiler prompt instructs the LLM to classify each claim explicitly. The
`CompiledClaim` model enforces the schema: `claim`, `confidence`, and optional
`quote`. Each article also receives an overall confidence level computed from
the ratio of sourced claims (>=80% sourced = SOURCED overall, >=40% = MIXED,
otherwise INFERRED).

In the wiki article `.md` file, claims are rendered with their confidence
inline: `**Claim text** *(sourced)*`. The UI surfaces confidence badges on
articles and individual claims.

## Alternatives Considered

**No confidence tagging** -- Simpler but makes the wiki unreliable. Users
cannot distinguish LLM fabrication from source material. This is a
non-starter for professionals whose "knowledge is their product."

**Binary sourced/unsourced** -- Too coarse. There is a meaningful difference
between "the LLM inferred this from context" and "the author explicitly stated
this as their opinion." The four-level scheme captures these distinctions.

**Numeric confidence scores (0.0-1.0)** -- More granular but harder for
users to interpret and for the LLM to produce consistently. Discrete
categories are easier to display in the UI and more reliable from the LLM.

**Source-only (no LLM inference)** -- Would produce a summary, not a wiki
article. The value of WikiMind is synthesis across sources, which requires
inference. Tagging the inference makes it transparent rather than hidden.

## Consequences

**Enables:**
- Users can trust sourced claims and scrutinize inferred ones
- The linter can flag articles with low confidence for review
- The Q&A agent can weight sourced claims higher in answers
- Contradiction detection can compare claims at the same confidence level
- The health dashboard shows confidence distribution across the wiki

**Constrains:**
- The LLM must be prompted carefully to produce consistent classifications;
  prompt engineering is critical for reliability
- The four-level enum may need expansion if new confidence levels emerge

**Risks:**
- LLMs may misclassify confidence levels, especially at the sourced/inferred
  boundary. Mitigated by including the optional `quote` field so users can
  verify sourced claims against the original text.
