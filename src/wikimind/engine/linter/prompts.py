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
