#!/usr/bin/env bash
# =============================================================================
# WikiMind v0.1.0 — Comprehensive API Evidence Test
# =============================================================================
#
# Tests all API endpoints against a running WikiMind instance.
# Idempotent: safe to run multiple times. Creates minimal test data,
# cleans up after itself, and never deletes pre-existing content.
#
# Usage:
#   ./api-test.sh                        # test against localhost:7842
#   ./api-test.sh https://wikimind.fly.dev # test against production
#
# Output: writes api-test-results.txt to the same directory as this script.
# =============================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:7842}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCRIPT_DIR/api-test-results.md"
PASS=0
FAIL=0
SKIP=0
TOTAL=0

# IDs populated during test run (for cleanup)
_SHARE_LINK_ID=""
_TAG_ID=""
_SAVED_SEARCH_ID=""
_SCHEMA_ID=""
_CAPTURE_ID=""
_TEXT_SOURCE_ID=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check() {
  local label="$1"
  local method="$2"
  local path="$3"
  shift 3
  local expect_code="${1:-200}"
  shift || true

  TOTAL=$((TOTAL + 1))
  local url="${BASE_URL}${path}"

  # Build curl args
  local -a curl_args=(-s -o /tmp/wm-body.json -w "%{http_code}" -X "$method")
  # Add remaining args (headers, data, etc.)
  while [[ $# -gt 0 ]]; do
    curl_args+=("$1")
    shift
  done
  curl_args+=("$url")

  local code
  code=$(curl "${curl_args[@]}" 2>/dev/null || echo "000")

  if [[ "$code" == "$expect_code" ]]; then
    PASS=$((PASS + 1))
    printf "  PASS  %-4s %-55s → %s\n" "$method" "$path" "$code"
    printf "| PASS | \`%s\` | \`%s\` | %s |\n" "$method" "$path" "$code" >> "$OUT"
  else
    FAIL=$((FAIL + 1))
    local body
    body=$(cat /tmp/wm-body.json 2>/dev/null | head -c 120 | tr '\n' ' ')
    printf "  FAIL  %-4s %-55s → %s (expected %s)\n" "$method" "$path" "$code" "$expect_code"
    printf "| **FAIL** | \`%s\` | \`%s\` | %s (expected %s) |\n" "$method" "$path" "$code" "$expect_code" >> "$OUT"
  fi
}

skip() {
  local label="$1"
  local reason="$2"
  TOTAL=$((TOTAL + 1))
  SKIP=$((SKIP + 1))
  printf "  SKIP  %-60s — %s\n" "$label" "$reason"
  printf "| SKIP | — | %s | *%s* |\n" "$label" "$reason" >> "$OUT"
}

section() {
  printf "\n━━━ %s ━━━\n" "$1"
  printf "\n## %s\n\n" "$1" >> "$OUT"
  printf "| Status | Method | Path | Code |\n" >> "$OUT"
  printf "|--------|--------|------|------|\n" >> "$OUT"
}

json_field() {
  python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('$1',''))" < /tmp/wm-body.json 2>/dev/null
}

json_first_id() {
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['$1'] if isinstance(d,list) and d else '')" < /tmp/wm-body.json 2>/dev/null
}

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

cat > "$OUT" << EOF
# WikiMind API Test Results

**Date:** $(date -u +"%Y-%m-%dT%H:%M:%SZ")
**Target:** \`$BASE_URL\`
**Script:** [api-test.sh](api-test.sh)

---

EOF

printf "WikiMind API Evidence Test\n"
printf "Target: %s\n" "$BASE_URL"
printf "Output: %s\n" "$OUT"

# ---------------------------------------------------------------------------
# 0. Health (no auth)
# ---------------------------------------------------------------------------
section "0. Health & Connectivity"

check "Health"                  GET  "/health"
check "Deep health"             GET  "/health/deep"

# ---------------------------------------------------------------------------
# 1. Auth
# ---------------------------------------------------------------------------
section "1. Authentication"

check "Get current user"        GET  "/auth/me"
check "Magic link request"      POST "/auth/magic-link" 200 \
  -H "Content-Type: application/json" -d '{"email":"test@evidence.local"}'
check "Auth tokens page"        GET  "/auth/tokens"
check "Auth tokens JS"          GET  "/auth/tokens.js"

skip "OAuth login redirect"     "requires browser redirect"
skip "OAuth callback"           "requires valid OAuth code"
skip "Magic link verify"        "requires valid token"
skip "Create API token"         "would create persistent token"
skip "Logout"                   "would end session"
skip "Delete account"           "destructive"

# ---------------------------------------------------------------------------
# 2. Ingest
# ---------------------------------------------------------------------------
section "2. Content Ingestion"

check "List sources"            GET  "/api/ingest/sources"

# Find an existing source ID
FIRST_SOURCE_ID=$(curl -s "$BASE_URL/api/ingest/sources" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['id'] if d else '')" 2>/dev/null)

if [[ -n "$FIRST_SOURCE_ID" ]]; then
  check "Get source"             GET  "/api/ingest/sources/$FIRST_SOURCE_ID"
  check "Get source detail"      GET  "/api/ingest/sources/$FIRST_SOURCE_ID/detail"
  check "Get source content"     GET  "/api/ingest/sources/$FIRST_SOURCE_ID/content"
  check "List source images"     GET  "/api/ingest/sources/$FIRST_SOURCE_ID/images"
else
  skip "Get source"              "no sources available"
  skip "Get source detail"       "no sources available"
  skip "Get source content"      "no sources available"
  skip "List source images"      "no sources available"
fi

# Ingest a small text source for testing (idempotent: dedup by content hash)
check "Ingest text"             POST "/api/ingest/text" 200 \
  -H "Content-Type: application/json" \
  -d '{"title":"API Test Evidence Note","content":"This is a test note created by the API evidence script. It verifies the text ingestion endpoint works correctly. WikiMind API test 2026."}'
_TEXT_SOURCE_ID=$(json_field "id")

# Find a PDF source for image testing
PDF_SOURCE_ID=$(curl -s "$BASE_URL/api/ingest/sources" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); srcs=[s for s in d if s.get('source_type')=='pdf']; print(srcs[0]['id'] if srcs else '')" 2>/dev/null)

if [[ -n "$PDF_SOURCE_ID" ]]; then
  check "Get PDF source images"  GET  "/api/ingest/sources/$PDF_SOURCE_ID/images"

  FIRST_IMAGE=$(curl -s "$BASE_URL/api/ingest/sources/$PDF_SOURCE_ID/images" 2>/dev/null | \
    python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['filename'] if d else '')" 2>/dev/null)
  if [[ -n "$FIRST_IMAGE" ]]; then
    check "Get source image file" GET  "/api/ingest/sources/$PDF_SOURCE_ID/images/$FIRST_IMAGE"
  else
    skip "Get source image file"  "PDF has no extracted images"
  fi
else
  skip "Get PDF source images"   "no PDF sources"
  skip "Get source image file"   "no PDF sources"
fi

skip "Ingest URL"               "would trigger LLM compilation (costly)"
skip "Ingest PDF"               "would trigger LLM compilation (costly)"
skip "Get source original"      "binary download; tested via browser"
skip "Delete source"            "destructive; would remove data"

# ---------------------------------------------------------------------------
# 3. Drafts
# ---------------------------------------------------------------------------
section "3. Draft Review"

if [[ -n "$FIRST_SOURCE_ID" ]]; then
  check "Get draft (may 404)"    GET  "/api/ingest/sources/$FIRST_SOURCE_ID/draft" 404
fi
skip "Approve draft"             "requires pending draft"
skip "Reject draft"              "requires pending draft"

# ---------------------------------------------------------------------------
# 4. Wiki & Articles
# ---------------------------------------------------------------------------
section "4. Wiki & Knowledge Base"

check "List articles"           GET  "/api/wiki/articles"
check "List articles (filter)"  GET  "/api/wiki/articles?page_type=source&limit=5"

FIRST_SLUG=$(curl -s "$BASE_URL/api/wiki/articles" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['slug'] if d else '')" 2>/dev/null)
FIRST_ARTICLE_ID=$(curl -s "$BASE_URL/api/wiki/articles" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['id'] if d else '')" 2>/dev/null)

if [[ -n "$FIRST_SLUG" ]]; then
  check "Get article (by slug)"  GET  "/api/wiki/articles/$FIRST_SLUG"
  check "Get article (by ID)"    GET  "/api/wiki/articles/$FIRST_ARTICLE_ID"
  check "Get relationships"      GET  "/api/wiki/articles/$FIRST_SLUG/relationships"
  check "Get article tags"       GET  "/api/wiki/articles/$FIRST_ARTICLE_ID/tags"
else
  skip "Get article"             "no articles"
  skip "Get relationships"       "no articles"
  skip "Get article tags"        "no articles"
fi

check "Get random article"      GET  "/api/wiki/articles/random"
check "Search articles"         GET  "/api/wiki/search?q=transformer&limit=5"
check "Get search facets"       GET  "/api/wiki/search/facets?q=transformer"
check "Resolve wikilinks"       GET  "/api/wiki/wikilinks/resolve?q=attention&limit=5"
check "Get knowledge graph"     GET  "/api/wiki/graph"
skip "Get wiki health"          "deprecated; use /lint/reports/latest"

skip "Create stub article"      "would create persistent data"
skip "Edit article"             "would modify existing article"
skip "Refresh article"          "would reset staleness timer"
skip "Recompile article"        "would trigger LLM compilation"

# ---------------------------------------------------------------------------
# 5. Concepts
# ---------------------------------------------------------------------------
section "5. Concept Taxonomy"

check "List concepts"           GET  "/api/wiki/concepts"

FIRST_CONCEPT=$(curl -s "$BASE_URL/api/wiki/concepts" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['name'] if isinstance(d,list) and d else '')" 2>/dev/null)

if [[ -n "$FIRST_CONCEPT" ]]; then
  check "Get concept"            GET  "/api/wiki/concepts/$FIRST_CONCEPT"
  check "Get concept articles"   GET  "/api/wiki/concepts/$FIRST_CONCEPT/articles"
else
  skip "Get concept"             "no concepts"
  skip "Get concept articles"    "no concepts"
fi

skip "Rebuild taxonomy"         "would trigger LLM call"

# ---------------------------------------------------------------------------
# 6. Contradictions
# ---------------------------------------------------------------------------
section "6. Contradictions & Quality"

check "List contradictions"     GET  "/api/wiki/contradictions"
check "List resolutions"        GET  "/api/wiki/contradiction-resolutions"

FIRST_CONTRADICTION=$(curl -s "$BASE_URL/api/wiki/contradictions" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['id'] if isinstance(d,list) and d else '')" 2>/dev/null)

if [[ -n "$FIRST_CONTRADICTION" ]]; then
  check "Get contradiction"      GET  "/api/wiki/contradictions/$FIRST_CONTRADICTION"
else
  skip "Get contradiction"       "no contradictions found"
fi

skip "Resolve contradiction"    "would modify state"

# ---------------------------------------------------------------------------
# 7. Export & Download
# ---------------------------------------------------------------------------
section "7. Export & Download"

if [[ -n "$FIRST_SLUG" ]]; then
  check "Download markdown"      GET  "/api/wiki/articles/$FIRST_ARTICLE_ID/export?format=markdown"
  check "Download JSON"          GET  "/api/wiki/articles/$FIRST_ARTICLE_ID/export?format=json"
  check "Invalid format (422)"   GET  "/api/wiki/articles/$FIRST_ARTICLE_ID/export?format=csv" 422
fi

skip "Export as PDF"             "requires wkhtmltopdf"
skip "Export full wiki"          "large download"

# ---------------------------------------------------------------------------
# 8. Sharing
# ---------------------------------------------------------------------------
section "8. Sharing & Public Access"

check "List share links"        GET  "/api/wiki/share-links"

if [[ -n "$FIRST_ARTICLE_ID" ]]; then
  # Create a share link (will clean up later)
  check "Create share link"      POST "/api/wiki/share-links" 201 \
    -H "Content-Type: application/json" \
    -d "{\"article_id\":\"$FIRST_ARTICLE_ID\",\"expires_in_days\":1}"
  _SHARE_LINK_ID=$(json_field "id")
  SHARE_TOKEN=$(json_field "token")

  if [[ -n "$SHARE_TOKEN" ]]; then
    check "Public article (HTML)" GET  "/public/articles/$SHARE_TOKEN"
    check "Public article (JSON)" GET  "/public/articles/$SHARE_TOKEN/json"
  fi

  check "List links (filtered)"  GET  "/api/wiki/share-links?article_id=$FIRST_ARTICLE_ID"
fi

check "Public 404"               GET  "/public/articles/nonexistent-token" 404

# ---------------------------------------------------------------------------
# 9. Synthesis
# ---------------------------------------------------------------------------
section "9. Synthesis"

check "List synthesis pages"    GET  "/api/wiki/synthesis"
check "Get suggestions"         GET  "/api/wiki/synthesis/suggestions"
check "Get suggestions (limit)" GET  "/api/wiki/synthesis/suggestions?limit=3"

# Get two article IDs for synthesis preview
ARTICLE_IDS=$(curl -s "$BASE_URL/api/wiki/articles?limit=3" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); ids=[a['id'] for a in d[:3]]; print(','.join(ids))" 2>/dev/null)
IFS=',' read -ra AID_ARR <<< "$ARTICLE_IDS"

if [[ ${#AID_ARR[@]} -ge 2 ]]; then
  check "Synthesis preview"      POST "/api/wiki/synthesis/preview" 200 \
    -H "Content-Type: application/json" \
    -d "{\"article_ids\":[\"${AID_ARR[0]}\",\"${AID_ARR[1]}\"],\"synthesis_type\":\"comparative\"}"
else
  skip "Synthesis preview"       "need 2+ articles"
fi

skip "Synthesis refine"          "requires previous preview draft"
skip "Synthesis confirm"         "would create persistent article"
skip "Create synthesis (direct)" "would trigger LLM call"

# ---------------------------------------------------------------------------
# 10. Query / Ask
# ---------------------------------------------------------------------------
section "10. Query & Conversations"

check "List conversations"      GET  "/api/query/conversations"
check "Query history"           GET  "/api/query/history?limit=5"

FIRST_CONVO=$(curl -s "$BASE_URL/api/query/conversations?limit=1" 2>/dev/null | \
  python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[0]['id'] if isinstance(d,list) and d else '')" 2>/dev/null)

if [[ -n "$FIRST_CONVO" ]]; then
  check "Get conversation"       GET  "/api/query/conversations/$FIRST_CONVO"
  check "Export conversation"    GET  "/api/query/conversations/$FIRST_CONVO/export"
fi

skip "Ask question"              "would trigger LLM call"
skip "Ask (streaming)"          "would trigger LLM call"
skip "Fork conversation"        "would trigger LLM call"
skip "File back"                "would create article"
skip "Crystallize"              "would trigger LLM call"

# ---------------------------------------------------------------------------
# 11. Tags
# ---------------------------------------------------------------------------
section "11. Tags"

check "List tags"               GET  "/api/tags"

# Create a test tag
check "Create tag"              POST "/api/tags" 201 \
  -H "Content-Type: application/json" \
  -d '{"name":"api-test-evidence","color":"#3b82f6"}'
_TAG_ID=$(json_field "id")

if [[ -n "$_TAG_ID" ]] && [[ -n "$FIRST_ARTICLE_ID" ]]; then
  check "Tag article"            POST "/api/wiki/articles/$FIRST_ARTICLE_ID/tags" 201 \
    -H "Content-Type: application/json" \
    -d "{\"tag_id\":\"$_TAG_ID\"}"
  check "Get articles by tag"    GET  "/api/tags/$_TAG_ID/articles"
  check "Untag article"          DELETE "/api/wiki/articles/$FIRST_ARTICLE_ID/tags/$_TAG_ID" 204
fi

# ---------------------------------------------------------------------------
# 12. Saved Searches
# ---------------------------------------------------------------------------
section "12. Saved Searches"

check "List saved searches"     GET  "/api/saved-searches"

check "Create saved search"     POST "/api/saved-searches" 201 \
  -H "Content-Type: application/json" \
  -d '{"name":"api-test-search","query":"transformer attention"}'
_SAVED_SEARCH_ID=$(json_field "id")

if [[ -n "$_SAVED_SEARCH_ID" ]]; then
  check "Execute saved search"   POST "/api/saved-searches/$_SAVED_SEARCH_ID/execute"
fi

# ---------------------------------------------------------------------------
# 13. Compilation Schemas
# ---------------------------------------------------------------------------
section "13. Compilation Schemas"

check "List schemas"            GET  "/api/compilation-schemas"

check "Create schema"           POST "/api/compilation-schemas" 201 \
  -H "Content-Type: application/json" \
  -d '{"name":"api-test-schema","description":"Test schema for evidence","is_active":false}'
_SCHEMA_ID=$(json_field "id")

if [[ -n "$_SCHEMA_ID" ]]; then
  check "Get schema"             GET  "/api/compilation-schemas/$_SCHEMA_ID"
  check "Update schema"          PATCH "/api/compilation-schemas/$_SCHEMA_ID" 200 \
    -H "Content-Type: application/json" \
    -d '{"description":"Updated test schema"}'
fi

# ---------------------------------------------------------------------------
# 14. Capture / Inbox
# ---------------------------------------------------------------------------
section "14. Ambient Capture"

check "List captures"           GET  "/api/capture"
check "List RSS feeds"          GET  "/api/capture/rss/feeds"

check "Create capture"          POST "/api/capture/clipboard" 200 \
  -H "Content-Type: application/json" \
  -d '{"content":"API test capture note for evidence","title":"Test Capture"}'
_CAPTURE_ID=$(json_field "id")

skip "Ingest capture"           "would trigger compilation"
skip "Subscribe RSS"            "would create persistent subscription"
skip "Poll RSS"                 "would fetch external content"

# ---------------------------------------------------------------------------
# 15. Jobs
# ---------------------------------------------------------------------------
section "15. Background Jobs"

check "List jobs"               GET  "/api/jobs"

skip "Trigger compile"          "would trigger LLM call"
skip "Trigger lint"             "would trigger LLM call"
skip "Trigger reindex"          "modifies search index"

# ---------------------------------------------------------------------------
# 16. Lint / Quality
# ---------------------------------------------------------------------------
section "16. Linting & Quality"

check "List lint reports"       GET  "/api/lint/reports"
check "Get latest report (404 if none)" GET "/api/lint/reports/latest" 404

skip "Run lint"                 "would trigger LLM call"
skip "Dismiss finding"          "would modify state"

# ---------------------------------------------------------------------------
# 17. Settings
# ---------------------------------------------------------------------------
section "17. Settings & Configuration"

check "Get all settings"        GET  "/api/settings"
check "Get cost summary"        GET  "/api/settings/llm/cost"
check "Get cost breakdown"      GET  "/api/settings/llm/cost/breakdown"
check "Get onboarding status"   GET  "/api/settings/onboarding-status"

skip "Set default provider"     "would change config"
skip "Update settings"          "would change config"
skip "Test LLM connection"      "would make external call"

# ---------------------------------------------------------------------------
# 18. API Keys (BYOK)
# ---------------------------------------------------------------------------
section "18. API Keys (BYOK)"

check "List API keys"           GET  "/api/settings/api-keys"

skip "Set API key"              "would store secret"
skip "Delete API key"           "destructive"

# ---------------------------------------------------------------------------
# 19. MCP Tokens
# ---------------------------------------------------------------------------
section "19. MCP Tokens"

check "List MCP tokens"         GET  "/api/settings/mcp-tokens"

skip "Create MCP token"         "would create persistent token"
skip "Revoke MCP token"         "destructive"

# ---------------------------------------------------------------------------
# 20. MCP OAuth
# ---------------------------------------------------------------------------
section "20. MCP OAuth"

check "OAuth metadata"          GET  "/.well-known/oauth-authorization-server"

skip "MCP authorize"            "requires browser interaction"
skip "MCP token exchange"       "requires valid auth code"
skip "MCP revoke"               "requires valid token"

# ---------------------------------------------------------------------------
# 21. Admin
# ---------------------------------------------------------------------------
section "21. Admin Dashboard"

check "Admin stats"             GET  "/api/admin/stats"
check "Admin orphans"           GET  "/api/admin/orphans"
check "Admin eligible concepts" GET  "/api/admin/concepts/eligible"
check "Admin stuck sources"     GET  "/api/admin/stuck-sources"
check "Admin Docling status"    GET  "/api/admin/docling-status"
check "Admin traces"            GET  "/api/admin/traces"

skip "Retry stuck source"       "would re-queue compilation"
skip "Sweep wikilinks"          "modifies graph"
skip "Reindex"                  "modifies search index"

# ---------------------------------------------------------------------------
# 22. Rate Limiting
# ---------------------------------------------------------------------------
section "22. Rate Limiting"

# Blast magic-link to trigger 429
for i in $(seq 1 7); do
  curl -s -o /dev/null "$BASE_URL/auth/magic-link" \
    -X POST -H "Content-Type: application/json" \
    -d '{"email":"ratelimit@test.local"}' 2>/dev/null
done
check "Rate limit (429)"        POST "/auth/magic-link" 429 \
  -H "Content-Type: application/json" -d '{"email":"ratelimit@test.local"}'

# ---------------------------------------------------------------------------
# 23. Error handling
# ---------------------------------------------------------------------------
section "23. Error Handling"

check "SPA fallback on unknown"  GET  "/api/nonexistent" 200
check "404 on bad article"      GET  "/api/wiki/articles/nonexistent-slug-12345" 404
check "422 on bad body"         POST "/api/ingest/text" 422 \
  -H "Content-Type: application/json" -d '{}'

# ---------------------------------------------------------------------------
# Cleanup: remove test artifacts
# ---------------------------------------------------------------------------
section "CLEANUP"

if [[ -n "$_SHARE_LINK_ID" ]]; then
  check "Delete test share link" DELETE "/api/wiki/share-links/$_SHARE_LINK_ID" 204
fi

if [[ -n "$_TAG_ID" ]]; then
  check "Delete test tag"        DELETE "/api/tags/$_TAG_ID" 204
fi

if [[ -n "$_SAVED_SEARCH_ID" ]]; then
  check "Delete saved search"    DELETE "/api/saved-searches/$_SAVED_SEARCH_ID" 204
fi

if [[ -n "$_SCHEMA_ID" ]]; then
  check "Delete test schema"     DELETE "/api/compilation-schemas/$_SCHEMA_ID" 204
fi

if [[ -n "$_CAPTURE_ID" ]]; then
  check "Discard test capture"   POST "/api/capture/$_CAPTURE_ID/discard" 200 \
    -H "Content-Type: application/json" -d '{}'
fi

if [[ -n "$_TEXT_SOURCE_ID" ]]; then
  check "Delete test source"     DELETE "/api/ingest/sources/$_TEXT_SOURCE_ID" 200
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf "\n---\n\n" >> "$OUT"
printf "## Summary\n\n" >> "$OUT"
printf "| Metric | Count |\n" >> "$OUT"
printf "|--------|-------|\n" >> "$OUT"
printf "| Total  | %d |\n" "$TOTAL" >> "$OUT"
printf "| Pass   | %d |\n" "$PASS" >> "$OUT"
printf "| Fail   | %d |\n" "$FAIL" >> "$OUT"
printf "| Skip   | %d |\n" "$SKIP" >> "$OUT"
printf "\n**Skip reasons:** Endpoints that trigger LLM calls, create persistent data, require browser OAuth, or are destructive are intentionally skipped. The test script is idempotent — all test artifacts are cleaned up.\n" >> "$OUT"

printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
printf "TOTAL: %d  |  PASS: %d  |  FAIL: %d  |  SKIP: %d\n" "$TOTAL" "$PASS" "$FAIL" "$SKIP"
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
printf "Results saved to: %s\n" "$OUT"

# Generate a standalone HTML version of the results
HTML_OUT="$SCRIPT_DIR/api-test-results.html"
cat > "$HTML_OUT" << 'HTMLHEAD'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>WikiMind API Test Results</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 2rem; max-width: 1000px; margin: 0 auto; }
  h1 { color: #58a6ff; font-size: 1.5rem; margin-bottom: 0.5rem; }
  .meta { color: #8b949e; font-size: 0.85rem; margin-bottom: 1.5rem; border-bottom: 1px solid #21262d; padding-bottom: 1rem; }
  .meta code { color: #79c0ff; background: #21262d; padding: 1px 5px; border-radius: 3px; }
  .stats { display: flex; gap: 1.5rem; margin-bottom: 1.5rem; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 0.75rem 1.5rem; text-align: center; }
  .stat .v { font-size: 1.5rem; font-weight: 700; } .stat .l { font-size: 0.7rem; color: #8b949e; }
  .green { color: #3fb950; } .red { color: #f85149; } .gray { color: #8b949e; }
  h2 { color: #f0883e; font-size: 1rem; margin: 1.5rem 0 0.5rem; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
  th { text-align: left; padding: 0.3rem 0.5rem; color: #8b949e; font-size: 0.75rem; border-bottom: 1px solid #30363d; }
  td { padding: 0.25rem 0.5rem; font-size: 0.78rem; border-bottom: 1px solid #161b22; }
  tr:hover { background: #161b22; }
  .pass { color: #3fb950; font-weight: 600; } .fail { color: #f85149; font-weight: 700; } .skip { color: #8b949e; }
  .m { color: #d2a8ff; font-family: monospace; font-size: 0.75rem; }
  .p { color: #79c0ff; font-family: monospace; font-size: 0.75rem; }
  .c { font-family: monospace; }
  a { color: #58a6ff; }
  footer { color: #484f58; font-size: 0.75rem; margin-top: 2rem; padding-top: 0.75rem; border-top: 1px solid #21262d; }
</style>
</head>
<body>
<h1>WikiMind API Test Results</h1>
HTMLHEAD

# Add metadata
cat >> "$HTML_OUT" << EOF
<div class="meta">
  <strong>Date:</strong> $(date -u +"%Y-%m-%dT%H:%M:%SZ") &nbsp;|&nbsp;
  <strong>Target:</strong> <code>$BASE_URL</code> &nbsp;|&nbsp;
  <a href="api-test.sh">Test script source</a> &nbsp;|&nbsp;
  <a href="index.html">Full evidence page</a>
</div>
<div class="stats">
  <div class="stat"><div class="v green">$PASS</div><div class="l">Pass</div></div>
  <div class="stat"><div class="v red">$FAIL</div><div class="l">Fail</div></div>
  <div class="stat"><div class="v gray">$SKIP</div><div class="l">Skip</div></div>
  <div class="stat"><div class="v">$TOTAL</div><div class="l">Total</div></div>
</div>
EOF

# Convert the markdown tables to HTML tables
python3 -c "
import re, html as h
with open('$OUT') as f:
    lines = f.readlines()

out = []
in_table = False
for line in lines:
    line = line.rstrip()
    if line.startswith('## '):
        if in_table:
            out.append('</table>')
            in_table = False
        out.append(f'<h2>{h.escape(line[3:])}</h2>')
        continue
    if line.startswith('|--'):
        continue
    if line.startswith('| Status'):
        out.append('<table><tr><th>Status</th><th>Method</th><th>Path</th><th>Code</th></tr>')
        in_table = True
        continue
    if line.startswith('|') and in_table:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 4:
            status_class = 'pass' if cells[0] == 'PASS' else ('fail' if 'FAIL' in cells[0] else 'skip')
            method = cells[1].replace('\`', '')
            path = cells[2].replace('\`', '')
            code = cells[3].replace('*', '').replace('\`', '')
            out.append(f'<tr><td class=\"{status_class}\">{cells[0].replace(\"**\",\"\")}</td><td class=\"m\">{h.escape(method)}</td><td class=\"p\">{h.escape(path)}</td><td class=\"c\">{h.escape(code)}</td></tr>')
        continue
    if line.startswith('---') or line.startswith('#') or line.startswith('**Date') or line.startswith('**Target') or line.startswith('**Script') or line.startswith('**Skip'):
        continue
    if line.startswith('| Metric'):
        continue

if in_table:
    out.append('</table>')

print('\n'.join(out))
" >> "$HTML_OUT"

cat >> "$HTML_OUT" << 'HTMLFOOT'
<footer>
  Generated by api-test.sh &nbsp;|&nbsp; WikiMind v0.1.0
</footer>
</body>
</html>
HTMLFOOT

printf "HTML results: %s\n" "$HTML_OUT"
