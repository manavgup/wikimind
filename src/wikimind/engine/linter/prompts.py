"""LLM prompt constants for the wiki linter."""

CONTRADICTION_SYSTEM_PROMPT = (
    "You are a wiki health auditor. Given two short wiki articles about the same topic, "
    "identify any contradictory assertions between their key claims. Return strict JSON."
)

CONTRADICTION_USER_TEMPLATE = """Article A: "{title_a}"
Key claims:
{claims_a}

Article B: "{title_b}"
Key claims:
{claims_b}

Return JSON of this shape:
{{
  "contradictions": [
    {{
      "description": "one-sentence summary of the contradiction",
      "article_a_claim": "the specific claim from A",
      "article_b_claim": "the specific claim from B",
      "confidence": "high" | "medium" | "low"
    }}
  ]
}}
If there are no contradictions, return {{"contradictions": []}}."""

# ---------------------------------------------------------------------------
# Batch contradiction detection (issue #138)
# ---------------------------------------------------------------------------

CONTRADICTION_BATCH_SYSTEM = (
    "You are a wiki health auditor. Given multiple pairs of wiki articles "
    "about the same topic, identify contradictory assertions between each pair's "
    "key claims. Return strict JSON: an array of objects, one per pair_index."
)

CONTRADICTION_BATCH_USER = """Compare the following {pair_count} article pairs for contradictions.

{pair_sections}

For each pair, return an object with this shape:
{{
  "pair_index": <int>,
  "contradictions": [
    {{
      "description": "one-sentence summary of the contradiction",
      "article_a_claim": "the specific claim from A",
      "article_b_claim": "the specific claim from B",
      "confidence": "high" | "medium" | "low"
    }}
  ]
}}

Return a JSON array of exactly {pair_count} objects. If a pair has no contradictions, return an empty contradictions array for that pair.
Example: [{{"pair_index": 0, "contradictions": []}}, {{"pair_index": 1, "contradictions": [...]}}]"""


def format_batch_pair_section(index: int, title_a: str, claims_a: str, title_b: str, claims_b: str) -> str:
    """Format a single pair section for the batch prompt."""
    return f"""--- Pair {index} ---
Article A: "{title_a}"
Key claims:
{claims_a}

Article B: "{title_b}"
Key claims:
{claims_b}"""
