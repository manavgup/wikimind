#!/usr/bin/env bash
# ===========================================================================
# Multi-User Data Isolation Test Script
# ===========================================================================
#
# End-to-end tests verifying that User A cannot see, modify, or delete
# User B's data.  Exercises the full pipeline: user creation → ingest →
# compile → articles → Q&A → file download → account deletion.
#
# ALL access is via the API — no direct database calls.
#
# Usage:
#   ./scripts/test-user-isolation.sh                   # default localhost:7842
#   ./scripts/test-user-isolation.sh https://wikimind.fly.dev
#
# Prerequisites:
#   - jq installed
#   - Python 3 with PyJWT (pip install pyjwt)
#   - Server running with WIKIMIND_AUTH__ENABLED=true
#   - WIKIMIND_AUTH__JWT_SECRET_KEY set (reads from .env)
#   - At least one LLM provider configured (for compilation + Q&A)
# ===========================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:7842}"
COOKIE_NAME="wikimind_session"
PASS=0
FAIL=0
TOTAL=0
MAX_WAIT=120   # seconds to wait for compilation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

red()   { printf "\033[31m%s\033[0m" "$*"; }
green() { printf "\033[32m%s\033[0m" "$*"; }
bold()  { printf "\033[1m%s\033[0m" "$*"; }
dim()   { printf "\033[2m%s\033[0m" "$*"; }

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "$actual" == "$expected" ]]; then
        PASS=$((PASS + 1))
        printf "  $(green PASS)  %s\n" "$label"
    else
        FAIL=$((FAIL + 1))
        printf "  $(red FAIL)  %s  (expected: %s, got: %s)\n" "$label" "$expected" "$actual"
    fi
}

assert_neq() {
    local label="$1" not_expected="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "$actual" != "$not_expected" ]]; then
        PASS=$((PASS + 1))
        printf "  $(green PASS)  %s\n" "$label"
    else
        FAIL=$((FAIL + 1))
        printf "  $(red FAIL)  %s  (should NOT be: %s)\n" "$label" "$not_expected"
    fi
}

assert_contains() {
    local label="$1" expected="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "$actual" == *"$expected"* ]]; then
        PASS=$((PASS + 1))
        printf "  $(green PASS)  %s\n" "$label"
    else
        FAIL=$((FAIL + 1))
        printf "  $(red FAIL)  %s  (expected to contain: %s, got: %s)\n" "$label" "$expected" "$actual"
    fi
}

assert_gt() {
    local label="$1" threshold="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "$actual" -gt "$threshold" ]]; then
        PASS=$((PASS + 1))
        printf "  $(green PASS)  %s\n" "$label"
    else
        FAIL=$((FAIL + 1))
        printf "  $(red FAIL)  %s  (expected > %s, got: %s)\n" "$label" "$threshold" "$actual"
    fi
}

info() {
    printf "        $(dim "→ %s")\n" "$*"
}

api() {
    # api <method> <path> [token] [data]
    local method="$1" path="$2" token="${3:-}" data="${4:-}"
    local -a args=(-s -X "$method")

    if [[ -n "$token" ]]; then
        args+=(-b "${COOKIE_NAME}=${token}")
    fi
    if [[ -n "$data" ]]; then
        args+=(-H "Content-Type: application/json" -d "$data")
    fi

    args+=("${BASE_URL}${path}")
    curl "${args[@]}"
}

api_status() {
    # Like api() but returns HTTP status code
    local method="$1" path="$2" token="${3:-}"
    local -a args=(-s -o /dev/null -w "%{http_code}" -X "$method")

    if [[ -n "$token" ]]; then
        args+=(-b "${COOKIE_NAME}=${token}")
    fi

    args+=("${BASE_URL}${path}")
    curl "${args[@]}"
}

wait_for_compilation() {
    # wait_for_compilation <source_id> <token> <label>
    local source_id="$1" token="$2" label="$3"
    local elapsed=0

    info "Waiting for $label to compile (max ${MAX_WAIT}s)..."
    while [[ $elapsed -lt $MAX_WAIT ]]; do
        local status
        status=$(api GET "/ingest/sources/$source_id" "$token" | jq -r '.status')
        if [[ "$status" == "compiled" ]]; then
            info "Compiled in ${elapsed}s"
            return 0
        elif [[ "$status" == "failed" ]]; then
            info "Compilation FAILED after ${elapsed}s"
            return 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        printf "        $(dim "→ %ss ... status=%s")\n" "$elapsed" "$status"
    done
    info "Timed out after ${MAX_WAIT}s (status=$status)"
    return 1
}

# ---------------------------------------------------------------------------
# Read JWT secret from .env
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

JWT_SECRET=""
if [[ -f "$REPO_ROOT/.env" ]]; then
    JWT_SECRET=$(grep -E '^WIKIMIND_AUTH__JWT_SECRET_KEY=' "$REPO_ROOT/.env" | cut -d= -f2- | tr -d '"' || true)
fi
if [[ -z "$JWT_SECRET" ]]; then
    echo "ERROR: WIKIMIND_AUTH__JWT_SECRET_KEY not found in .env"
    echo "       Set it or pass via: JWT_SECRET=... $0"
    exit 1
fi

# ---------------------------------------------------------------------------
# Generate JWTs for two test users
# ---------------------------------------------------------------------------

mint_jwt() {
    python3 -c "import jwt; print(jwt.encode({'sub':'$1', 'email':'$1@test.local'}, '$JWT_SECRET', algorithm='HS256'))"
}

USER_A_ID="test-user-a-$(date +%s)"
USER_B_ID="test-user-b-$(date +%s)"
TOKEN_A=$(mint_jwt "$USER_A_ID")
TOKEN_B=$(mint_jwt "$USER_B_ID")

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

echo ""
bold "================================================================"
echo ""
bold "  Multi-User Data Isolation Tests"
echo ""
bold "================================================================"
echo ""
echo "  Server:   $BASE_URL"
echo "  User A:   $USER_A_ID"
echo "  User B:   $USER_B_ID"
echo "  Token A:  ${TOKEN_A:0:20}..."
echo "  Token B:  ${TOKEN_B:0:20}..."
echo ""

# Check server is reachable
HEALTH=$(curl -sf "${BASE_URL}/health" 2>/dev/null || true)
if [[ -z "$HEALTH" ]]; then
    echo "ERROR: Server not reachable at $BASE_URL"
    exit 1
fi
echo "  Health:   $(echo "$HEALTH" | jq -r '.status')"

# Check auth is enabled
UNAUTH=$(api GET "/ingest/sources" "" "" 2>/dev/null)
if echo "$UNAUTH" | jq -e '.error.code == "UNAUTHORIZED"' > /dev/null 2>&1; then
    echo "  Auth:     enabled"
else
    echo "  ERROR: Auth is not enabled — cannot test isolation"
    exit 1
fi

# ===========================================================================
# Setup: Create test users via GET /auth/me (auto-provision)
# ===========================================================================

echo ""
bold "Setup: Creating test users via API"
echo ""

USER_A_RESP=$(api GET "/auth/me" "$TOKEN_A")
USER_A_DB_ID=$(echo "$USER_A_RESP" | jq -r '.id')
assert_eq "GET /auth/me auto-provisions User A" "$USER_A_ID" "$USER_A_DB_ID"
info "User A: id=$USER_A_DB_ID  email=$(echo "$USER_A_RESP" | jq -r '.email')  name=$(echo "$USER_A_RESP" | jq -r '.name')"

USER_B_RESP=$(api GET "/auth/me" "$TOKEN_B")
USER_B_DB_ID=$(echo "$USER_B_RESP" | jq -r '.id')
assert_eq "GET /auth/me auto-provisions User B" "$USER_B_ID" "$USER_B_DB_ID"
info "User B: id=$USER_B_DB_ID  email=$(echo "$USER_B_RESP" | jq -r '.email')  name=$(echo "$USER_B_RESP" | jq -r '.name')"

# Calling /auth/me again should return the same user (not create a duplicate)
USER_A_AGAIN=$(api GET "/auth/me" "$TOKEN_A" | jq -r '.id')
assert_eq "GET /auth/me is idempotent for User A" "$USER_A_ID" "$USER_A_AGAIN"

# ===========================================================================
# Test Group 1: Unauthenticated access is blocked
# ===========================================================================

echo ""
bold "1. Unauthenticated access is blocked"
echo ""

RESP=$(api GET "/ingest/sources")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /ingest/sources without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"
info "Response: $(echo "$RESP" | jq -c .)"

RESP=$(api GET "/wiki/articles")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /wiki/articles without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/query/conversations")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /query/conversations without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/settings")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /settings without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/jobs")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /jobs without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

# ===========================================================================
# Test Group 2: Ingest sources with auto_compile=true
# ===========================================================================

echo ""
bold "2. Ingest sources (with compilation)"
echo ""

SRC_A1=$(api POST "/ingest/text" "$TOKEN_A" \
    '{"content":"The Eiffel Tower is a wrought-iron lattice tower in Paris, France. It was constructed from 1887 to 1889 as the centerpiece of the 1889 World Fair. Named after engineer Gustave Eiffel, it stands 330 meters tall and is the most-visited paid monument in the world.","title":"Eiffel Tower Facts","auto_compile":true}')
SRC_A1_ID=$(echo "$SRC_A1" | jq -r '.id')
SRC_A1_UID=$(echo "$SRC_A1" | jq -r '.user_id')
assert_eq "Ingest as User A → user_id matches" "$USER_A_ID" "$SRC_A1_UID"
info "Source A1: id=$SRC_A1_ID  user_id=$SRC_A1_UID  title=$(echo "$SRC_A1" | jq -r '.title')"

SRC_A2=$(api POST "/ingest/text" "$TOKEN_A" \
    '{"content":"The Great Wall of China stretches over 13,000 miles across northern China.","title":"Great Wall Facts","auto_compile":false}')
SRC_A2_ID=$(echo "$SRC_A2" | jq -r '.id')
assert_neq "Ingest source 2 as User A → has ID" "null" "$SRC_A2_ID"
info "Source A2: id=$SRC_A2_ID  title=$(echo "$SRC_A2" | jq -r '.title')  (no compile)"

SRC_B1=$(api POST "/ingest/text" "$TOKEN_B" \
    '{"content":"Mount Fuji is the tallest mountain in Japan at 3,776 meters. It is an active stratovolcano that last erupted in 1707. It is one of Japans Three Holy Mountains.","title":"Mount Fuji Facts","auto_compile":true}')
SRC_B1_ID=$(echo "$SRC_B1" | jq -r '.id')
SRC_B1_UID=$(echo "$SRC_B1" | jq -r '.user_id')
assert_eq "Ingest as User B → user_id matches" "$USER_B_ID" "$SRC_B1_UID"
info "Source B1: id=$SRC_B1_ID  user_id=$SRC_B1_UID  title=$(echo "$SRC_B1" | jq -r '.title')"

# ===========================================================================
# Test Group 3: Wait for compilation to finish
# ===========================================================================

echo ""
bold "3. Wait for compilation"
echo ""

wait_for_compilation "$SRC_A1_ID" "$TOKEN_A" "User A source" || true
wait_for_compilation "$SRC_B1_ID" "$TOKEN_B" "User B source" || true

# ===========================================================================
# Test Group 4: Source list isolation
# ===========================================================================

echo ""
bold "4. Source list isolation"
echo ""

A_SOURCES=$(api GET "/ingest/sources" "$TOKEN_A")
A_COUNT=$(echo "$A_SOURCES" | jq 'length')
assert_eq "User A sees exactly 2 sources" "2" "$A_COUNT"
info "User A sources: $(echo "$A_SOURCES" | jq -c '[.[] | {id: .id, title: .title, status: .status}]')"

B_SOURCES=$(api GET "/ingest/sources" "$TOKEN_B")
B_COUNT=$(echo "$B_SOURCES" | jq 'length')
assert_eq "User B sees exactly 1 source" "1" "$B_COUNT"
info "User B sources: $(echo "$B_SOURCES" | jq -c '[.[] | {id: .id, title: .title, status: .status}]')"

# ===========================================================================
# Test Group 5: Cross-user source access is blocked
# ===========================================================================

echo ""
bold "5. Cross-user source access is blocked"
echo ""

RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_A")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User A GET User B's source ($SRC_B1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B GET User A's source ($SRC_A1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User A GET own source → success" "Eiffel Tower Facts" "$TITLE"
info "id=$SRC_A1_ID  title=$TITLE  user_id=$(echo "$RESP" | jq -r '.user_id')"

RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_B")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User B GET own source → success" "Mount Fuji Facts" "$TITLE"
info "id=$SRC_B1_ID  title=$TITLE  user_id=$(echo "$RESP" | jq -r '.user_id')"

# ===========================================================================
# Test Group 6: Original file download isolation
# ===========================================================================

echo ""
bold "6. Original file download isolation"
echo ""

STATUS_A_OWN=$(api_status GET "/ingest/sources/$SRC_A1_ID/original" "$TOKEN_A")
info "User A GET own source original → HTTP $STATUS_A_OWN"

STATUS_B_CROSS=$(api_status GET "/ingest/sources/$SRC_A1_ID/original" "$TOKEN_B")
assert_eq "User B GET User A's original → 404" "404" "$STATUS_B_CROSS"
info "User B cross-access → HTTP $STATUS_B_CROSS"

STATUS_A_CROSS=$(api_status GET "/ingest/sources/$SRC_B1_ID/original" "$TOKEN_A")
assert_eq "User A GET User B's original → 404" "404" "$STATUS_A_CROSS"
info "User A cross-access → HTTP $STATUS_A_CROSS"

# ===========================================================================
# Test Group 7: Article isolation (post-compilation)
# ===========================================================================

echo ""
bold "7. Article isolation (post-compilation)"
echo ""

A_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_A")
A_ART_COUNT=$(echo "$A_ARTICLES" | jq 'length')
info "User A article count: $A_ART_COUNT"
if [[ "$A_ART_COUNT" -gt 0 ]]; then
    info "User A articles: $(echo "$A_ARTICLES" | jq -c '[.[] | {slug, title}]')"
fi

B_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_B")
B_ART_COUNT=$(echo "$B_ARTICLES" | jq 'length')
info "User B article count: $B_ART_COUNT"
if [[ "$B_ART_COUNT" -gt 0 ]]; then
    info "User B articles: $(echo "$B_ARTICLES" | jq -c '[.[] | {slug, title}]')"
fi

# Cross-check: User B should NOT see User A's articles
if [[ "$A_ART_COUNT" -gt 0 ]]; then
    A_SLUG=$(echo "$A_ARTICLES" | jq -r '.[0].slug')
    A_ART_ID=$(echo "$A_ARTICLES" | jq -r '.[0].id')

    RESP_A_OWN=$(api GET "/wiki/articles/$A_SLUG" "$TOKEN_A")
    assert_contains "User A can read own article ($A_SLUG)" "title" "$RESP_A_OWN"
    info "User A article: slug=$A_SLUG  title=$(echo "$RESP_A_OWN" | jq -r '.title')"

    RESP_B_CROSS=$(api GET "/wiki/articles/$A_SLUG" "$TOKEN_B")
    DETAIL=$(echo "$RESP_B_CROSS" | jq -r '.detail // empty')
    assert_eq "User B GET User A's article ($A_SLUG) → 404" "Article not found" "$DETAIL"
    info "User B cross-access: $(echo "$RESP_B_CROSS" | jq -c .)"

    RESP_B_ID=$(api GET "/wiki/articles/$A_ART_ID" "$TOKEN_B")
    DETAIL_ID=$(echo "$RESP_B_ID" | jq -r '.detail // empty')
    assert_eq "User B GET User A's article by ID ($A_ART_ID) → 404" "Article not found" "$DETAIL_ID"
    info "User B cross-access by ID: $(echo "$RESP_B_ID" | jq -c .)"
else
    info "SKIPPED: No articles compiled for User A (LLM may not be configured)"
fi

if [[ "$B_ART_COUNT" -gt 0 ]]; then
    B_SLUG=$(echo "$B_ARTICLES" | jq -r '.[0].slug')
    RESP_A_CROSS=$(api GET "/wiki/articles/$B_SLUG" "$TOKEN_A")
    DETAIL=$(echo "$RESP_A_CROSS" | jq -r '.detail // empty')
    assert_eq "User A GET User B's article ($B_SLUG) → 404" "Article not found" "$DETAIL"
    info "User A cross-access: $(echo "$RESP_A_CROSS" | jq -c .)"
else
    info "SKIPPED: No articles compiled for User B (LLM may not be configured)"
fi

# ===========================================================================
# Test Group 8: Cross-user deletion is blocked
# ===========================================================================

echo ""
bold "8. Cross-user deletion is blocked"
echo ""

RESP=$(api DELETE "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B DELETE User A's source ($SRC_A1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User A's source survives User B's delete attempt" "Eiffel Tower Facts" "$TITLE"
info "Source still exists: id=$SRC_A1_ID  title=$TITLE"

RESP=$(api DELETE "/ingest/sources/$SRC_B1_ID" "$TOKEN_A")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User A DELETE User B's source ($SRC_B1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_B")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User B's source survives User A's delete attempt" "Mount Fuji Facts" "$TITLE"
info "Source still exists: id=$SRC_B1_ID  title=$TITLE"

# ===========================================================================
# Test Group 9: Q&A conversation isolation
# ===========================================================================

echo ""
bold "9. Q&A conversation isolation"
echo ""

if [[ "$A_ART_COUNT" -gt 0 ]]; then
    QA_A=$(api POST "/query" "$TOKEN_A" '{"question":"What is the Eiffel Tower?"}')
    CONV_A_ID=$(echo "$QA_A" | jq -r '.conversation.id // empty')
    if [[ -n "$CONV_A_ID" && "$CONV_A_ID" != "null" ]]; then
        assert_neq "User A asked question → got conversation" "null" "$CONV_A_ID"
        info "User A conversation: id=$CONV_A_ID"
        info "Answer preview: $(echo "$QA_A" | jq -r '.query.answer // empty' | head -c 100)..."

        RESP=$(api GET "/query/conversations/$CONV_A_ID" "$TOKEN_A")
        assert_contains "User A can view own conversation" "queries" "$RESP"
        info "User A conversation: $(echo "$RESP" | jq -c '{id: .conversation.id, title: .conversation.title}')"

        RESP=$(api GET "/query/conversations/$CONV_A_ID" "$TOKEN_B")
        DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
        assert_eq "User B GET User A's conversation ($CONV_A_ID) → 404" "Conversation not found" "$DETAIL"
        info "User B cross-access: $(echo "$RESP" | jq -c .)"

        STATUS=$(api_status GET "/query/conversations/$CONV_A_ID/export" "$TOKEN_B")
        assert_eq "User B export User A's conversation → 404" "404" "$STATUS"
        info "User B export attempt → HTTP $STATUS"

        A_CONV_COUNT=$(api GET "/query/conversations" "$TOKEN_A" | jq 'length')
        B_CONV_COUNT=$(api GET "/query/conversations" "$TOKEN_B" | jq 'length')
        assert_gt "User A has conversations" "0" "$A_CONV_COUNT"
        assert_eq "User B has 0 conversations" "0" "$B_CONV_COUNT"
        info "User A conversations: $A_CONV_COUNT  |  User B conversations: $B_CONV_COUNT"
    else
        info "SKIPPED: Q&A returned no conversation (LLM may have failed)"
    fi
else
    info "SKIPPED: No articles for User A — Q&A requires compiled articles"
fi

# ===========================================================================
# Test Group 10: Search isolation
# ===========================================================================

echo ""
bold "10. Search isolation"
echo ""

if [[ "$A_ART_COUNT" -gt 0 ]]; then
    A_SEARCH=$(api GET "/wiki/search?q=eiffel" "$TOKEN_A")
    A_SEARCH_COUNT=$(echo "$A_SEARCH" | jq 'length')
    info "User A search 'eiffel': $A_SEARCH_COUNT results"

    B_SEARCH=$(api GET "/wiki/search?q=eiffel" "$TOKEN_B")
    B_SEARCH_COUNT=$(echo "$B_SEARCH" | jq 'length')
    assert_eq "User B search for User A's content → 0 results" "0" "$B_SEARCH_COUNT"
    info "User B search 'eiffel': $B_SEARCH_COUNT results"
else
    info "SKIPPED: No articles to search"
fi

# ===========================================================================
# Test Group 11: Knowledge graph isolation
# ===========================================================================

echo ""
bold "11. Knowledge graph isolation"
echo ""

A_GRAPH=$(api GET "/wiki/graph" "$TOKEN_A")
A_NODE_COUNT=$(echo "$A_GRAPH" | jq '.nodes | length')
info "User A graph nodes: $A_NODE_COUNT"

B_GRAPH=$(api GET "/wiki/graph" "$TOKEN_B")
B_NODE_COUNT=$(echo "$B_GRAPH" | jq '.nodes | length')
info "User B graph nodes: $B_NODE_COUNT"

if [[ "$A_NODE_COUNT" -gt 0 ]] && [[ "$A_ART_COUNT" -gt 0 ]]; then
    A_FIRST_TITLE=$(echo "$A_ARTICLES" | jq -r '.[0].title' 2>/dev/null || echo "")
    if [[ -n "$A_FIRST_TITLE" ]]; then
        B_HAS_A_TITLE=$(echo "$B_GRAPH" | jq --arg t "$A_FIRST_TITLE" '[.nodes[] | select(.label == $t)] | length')
        assert_eq "User B's graph does not contain User A's articles" "0" "$B_HAS_A_TITLE"
    fi
fi

# ===========================================================================
# Test Group 12: Protected endpoints require auth
# ===========================================================================

echo ""
bold "12. Protected endpoints require auth"
echo ""

RESP=$(api GET "/settings" "$TOKEN_A")
assert_contains "GET /settings with auth → returns LLM config" "default_provider" "$RESP"
info "Provider: $(echo "$RESP" | jq -r '.llm.default_provider')"

RESP=$(api GET "/jobs" "$TOKEN_A")
assert_eq "GET /jobs with auth → returns array" "true" "$(echo "$RESP" | jq 'type == "array"')"
info "Job count: $(echo "$RESP" | jq 'length')"

RESP=$(api GET "/lint/reports" "$TOKEN_A")
assert_eq "GET /lint/reports with auth → returns array" "true" "$(echo "$RESP" | jq 'type == "array"')"
info "Report count: $(echo "$RESP" | jq 'length')"

# ===========================================================================
# Test Group 13: WebSocket auth (source code verification)
# ===========================================================================

echo ""
bold "13. WebSocket auth (source code verification)"
echo ""

if grep -qF 'query_params.get("user_id")' src/wikimind/api/routes/ws.py 2>/dev/null; then
    assert_eq "ws.py does NOT read user_id from query params" "gone" "still present"
else
    assert_eq "ws.py does NOT read user_id from query params" "gone" "gone"
fi
info "ws.py uses get_ws_user_id() for JWT-based auth"

if grep -q 'get_ws_user_id' src/wikimind/api/deps.py 2>/dev/null; then
    assert_eq "get_ws_user_id helper exists in deps.py" "found" "found"
else
    assert_eq "get_ws_user_id helper exists in deps.py" "found" "missing"
fi

# ===========================================================================
# Cleanup: DELETE /auth/account removes all user data via API
# ===========================================================================

echo ""
bold "Cleanup: Delete accounts via API"
echo ""

RESP_A=$(api DELETE "/auth/account" "$TOKEN_A")
DELETED_A=$(echo "$RESP_A" | jq -r '.deleted // empty')
assert_eq "DELETE /auth/account removes User A" "$USER_A_ID" "$DELETED_A"
info "User A deleted: $(echo "$RESP_A" | jq -c .)"

RESP_B=$(api DELETE "/auth/account" "$TOKEN_B")
DELETED_B=$(echo "$RESP_B" | jq -r '.deleted // empty')
assert_eq "DELETE /auth/account removes User B" "$USER_B_ID" "$DELETED_B"
info "User B deleted: $(echo "$RESP_B" | jq -c .)"

# Verify the accounts are gone
STATUS_A=$(api_status GET "/auth/me" "$TOKEN_A")
# /auth/me now auto-provisions, so a GET would re-create the user.
# Instead, verify their sources are gone.
A_AFTER=$(api GET "/ingest/sources" "$TOKEN_A" | jq 'length')
B_AFTER=$(api GET "/ingest/sources" "$TOKEN_B" | jq 'length')
assert_eq "User A has 0 sources after account deletion" "0" "$A_AFTER"
assert_eq "User B has 0 sources after account deletion" "0" "$B_AFTER"
info "Post-deletion: User A sources=$A_AFTER  User B sources=$B_AFTER"

# Clean up the auto-provisioned users from the verification step above
api DELETE "/auth/account" "$TOKEN_A" > /dev/null 2>&1 || true
api DELETE "/auth/account" "$TOKEN_B" > /dev/null 2>&1 || true

# ===========================================================================
# Summary
# ===========================================================================

echo ""
echo "==========================================="
if [[ $FAIL -eq 0 ]]; then
    green "  ALL $TOTAL TESTS PASSED"
else
    red "  $FAIL/$TOTAL TESTS FAILED"
fi
echo ""
echo "==========================================="
echo ""

exit "$FAIL"
