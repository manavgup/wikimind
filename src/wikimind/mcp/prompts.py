"""MCP prompts for the WikiMind server.

Prompts instruct the LLM to use tools in sequence. They do NOT pre-compute
data — the LLM handles errors naturally via tool calls.

Prompts:
  - wiki_onboarding: no params, instructs tool usage
  - research_topic(topic): instructs search -> read -> synthesize
  - compare_articles(slug_a, slug_b): instructs fetch both + compare
  - knowledge_gaps(topic?): with/without topic variants
"""

from __future__ import annotations

from wikimind.mcp.server import mcp

# ---------------------------------------------------------------------------
# Prompt: wiki_onboarding
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="wiki_onboarding",
    description="Get oriented with your WikiMind knowledge base",
)
async def prompt_onboarding() -> str:
    """Generate an onboarding prompt that instructs tool usage."""
    return (
        "The user has connected to their WikiMind knowledge base.\n\n"
        "1. Call wiki_overview() to understand what's in the knowledge base\n"
        "2. Summarize the wiki's scope in 2-3 sentences\n"
        "3. List the major topic areas with article counts\n"
        "4. Highlight the 3 most recent or substantial articles\n"
        "5. Suggest 3 questions the user could ask based on the wiki's contents\n"
        "6. Note any areas that seem underdeveloped"
    )


# ---------------------------------------------------------------------------
# Prompt: research_topic
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="research_topic",
    description="Research a topic using your WikiMind knowledge base",
)
async def prompt_research_topic(topic: str) -> str:
    """Generate a research prompt for a topic."""
    return (
        f'Research "{topic}" using the WikiMind knowledge base.\n\n'
        f'1. Call wiki_search("{topic}") to find relevant articles\n'
        "2. For each relevant result, call wiki_get_article(slug) to read the content\n"
        "3. Synthesize findings into a comprehensive overview\n"
        "4. Identify what the wiki covers well vs what's missing\n"
        "5. Suggest follow-up questions or areas to explore"
    )


# ---------------------------------------------------------------------------
# Prompt: compare_articles
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="compare_articles",
    description="Compare two wiki articles",
)
async def prompt_compare_articles(slug_a: str, slug_b: str) -> str:
    """Generate a comparison prompt for two articles."""
    return (
        "Compare these two WikiMind articles.\n\n"
        f'1. Call wiki_get_article("{slug_a}") and wiki_get_article("{slug_b}")\n'
        "2. Identify key agreements between the articles\n"
        "3. Identify disagreements or contradictions\n"
        "4. Highlight what each article covers that the other doesn't\n"
        "5. Suggest whether a synthesis would be valuable"
    )


# ---------------------------------------------------------------------------
# Prompt: knowledge_gaps
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="knowledge_gaps",
    description="Find gaps in your WikiMind knowledge base",
)
async def prompt_knowledge_gaps(topic: str = "") -> str:
    """Generate a knowledge gaps analysis prompt."""
    if topic:
        return (
            f'Analyze knowledge gaps about "{topic}" in the WikiMind knowledge base.\n\n'
            f'1. Call wiki_search("{topic}") to find existing coverage\n'
            "2. Call wiki_get_health() to check overall wiki quality\n"
            "3. Identify: topics not covered, articles with low confidence,\n"
            "   stale content, missing connections between related articles\n"
            "4. Prioritize gaps by importance\n"
            "5. Suggest sources or topics to add"
        )
    return (
        "Analyze the overall health and gaps of the WikiMind knowledge base.\n\n"
        "1. Call wiki_overview() to understand scope\n"
        "2. Call wiki_get_health() to get quality metrics\n"
        "3. Identify: orphaned articles, stale content, contradictions,\n"
        "   topics with thin coverage\n"
        "4. Prioritize issues by impact\n"
        "5. Recommend actions to improve the knowledge base"
    )
