#!/usr/bin/env bash
# ===========================================================================
# Multi-User Data Isolation Test Script
# ===========================================================================
#
# Tests that User A cannot see, modify, or delete User B's data and vice
# versa.  Requires the production stack (make deploy-up) with auth enabled.
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
# ===========================================================================

set -euo pipefail

BASE_URL="${1:-http://localhost:7842}"
COOKIE_NAME="wikimind_session"
PASS=0
FAIL=0
TOTAL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

red()   { printf "\033[31m%s\033[0m" "$*"; }
green() { printf "\033[32m%s\033[0m" "$*"; }
bold()  { printf "\033[1m%s\033[0m" "$*"; }

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
    python3 -c "import jwt; print(jwt.encode({'sub':'$1'}, '$JWT_SECRET', algorithm='HS256'))"
}

USER_A_ID="test-user-a-$(date +%s)"
USER_B_ID="test-user-b-$(date +%s)"
TOKEN_A=$(mint_jwt "$USER_A_ID")
TOKEN_B=$(mint_jwt "$USER_B_ID")

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

echo ""
bold "Multi-User Data Isolation Tests"
echo ""
echo "  Server:  $BASE_URL"
echo "  User A:  $USER_A_ID"
echo "  User B:  $USER_B_ID"
echo ""

# Check server is reachable
HEALTH=$(curl -sf "${BASE_URL}/health" 2>/dev/null || true)
if [[ -z "$HEALTH" ]]; then
    echo "ERROR: Server not reachable at $BASE_URL"
    exit 1
fi

# Check auth is enabled
UNAUTH=$(api GET "/ingest/sources" "" "" 2>/dev/null)
if echo "$UNAUTH" | jq -e '.error.code == "UNAUTHORIZED"' > /dev/null 2>&1; then
    echo "  Auth:    enabled"
else
    echo "  WARNING: Auth may not be enabled — tests may not be meaningful"
fi

# ---------------------------------------------------------------------------
# Create test users in the database
# ---------------------------------------------------------------------------

echo ""
bold "Setup: Creating test users"
echo ""

# Use the Postgres container to insert users directly.  The docker-compose
# service name is "postgres" in both dev and prod compose files.
COMPOSE_FILE="docker-compose.prod.yml"
if ! docker compose -f "$COMPOSE_FILE" ps postgres --status running -q > /dev/null 2>&1; then
    COMPOSE_FILE="docker-compose.yml"
fi

docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U wikimind -d wikimind -q -c "
    INSERT INTO \"user\" (id, email, name, auth_provider, auth_provider_id, created_at, updated_at)
    VALUES
        ('${USER_A_ID}', '${USER_A_ID}@test.local', 'Test User A', 'test', '${USER_A_ID}', NOW(), NOW()),
        ('${USER_B_ID}', '${USER_B_ID}@test.local', 'Test User B', 'test', '${USER_B_ID}', NOW(), NOW())
    ON CONFLICT (id) DO NOTHING;
" 2>/dev/null

echo "  Created User A and User B in database"

# ===========================================================================
# Test Group 1: Unauthenticated access is blocked
# ===========================================================================

echo ""
bold "1. Unauthenticated access"
echo ""

RESP=$(api GET "/ingest/sources")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /ingest/sources without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/wiki/articles")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /wiki/articles without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/query/conversations")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /query/conversations without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

# ===========================================================================
# Test Group 2: Source isolation (ingest)
# ===========================================================================

echo ""
bold "2. Source isolation"
echo ""

# User A ingests two sources
SRC_A1=$(api POST "/ingest/text" "$TOKEN_A" '{"content":"User A secret document one","title":"A-Doc-1","auto_compile":false}')
SRC_A1_ID=$(echo "$SRC_A1" | jq -r '.id')
SRC_A1_UID=$(echo "$SRC_A1" | jq -r '.user_id')
assert_eq "Ingest source 1 as User A → user_id matches" "$USER_A_ID" "$SRC_A1_UID"

SRC_A2=$(api POST "/ingest/text" "$TOKEN_A" '{"content":"User A secret document two","title":"A-Doc-2","auto_compile":false}')
SRC_A2_ID=$(echo "$SRC_A2" | jq -r '.id')
assert_eq "Ingest source 2 as User A → has ID" "true" "$([ -n "$SRC_A2_ID" ] && [ "$SRC_A2_ID" != "null" ] && echo true || echo false)"

# User B ingests one source
SRC_B1=$(api POST "/ingest/text" "$TOKEN_B" '{"content":"User B private note","title":"B-Doc-1","auto_compile":false}')
SRC_B1_ID=$(echo "$SRC_B1" | jq -r '.id')
SRC_B1_UID=$(echo "$SRC_B1" | jq -r '.user_id')
assert_eq "Ingest source as User B → user_id matches" "$USER_B_ID" "$SRC_B1_UID"

# User A sees only their sources
A_COUNT=$(api GET "/ingest/sources" "$TOKEN_A" | jq 'length')
assert_eq "User A source list count → 2" "2" "$A_COUNT"

# User B sees only their source
B_COUNT=$(api GET "/ingest/sources" "$TOKEN_B" | jq 'length')
assert_eq "User B source list count → 1" "1" "$B_COUNT"

# User A cannot access User B's source
RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_A")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User A GET User B's source → Source not found" "Source not found" "$DETAIL"

# User B cannot access User A's source
RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B GET User A's source → Source not found" "Source not found" "$DETAIL"

# User B cannot delete User A's source
RESP=$(api DELETE "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B DELETE User A's source → Source not found" "Source not found" "$DETAIL"

# User A's source still exists after B's delete attempt
RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User A's source survives User B's delete attempt" "A-Doc-1" "$TITLE"

# ===========================================================================
# Test Group 3: Article isolation (wiki)
# ===========================================================================

echo ""
bold "3. Article isolation"
echo ""

# User A's articles
A_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_A" | jq 'length')
# User B's articles
B_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_B" | jq 'length')
assert_eq "User B cannot see User A's articles" "0" "$B_ARTICLES"

# ===========================================================================
# Test Group 4: Conversation isolation (Q&A)
# ===========================================================================

echo ""
bold "4. Conversation isolation"
echo ""

A_CONVOS=$(api GET "/query/conversations" "$TOKEN_A" | jq 'length')
B_CONVOS=$(api GET "/query/conversations" "$TOKEN_B" | jq 'length')
assert_eq "User B has no conversations" "0" "$B_CONVOS"

# ===========================================================================
# Test Group 5: Settings / jobs endpoints require auth
# ===========================================================================

echo ""
bold "5. Protected endpoints"
echo ""

RESP=$(api GET "/settings" "$TOKEN_A")
assert_contains "GET /settings with auth → returns data" "llm" "$RESP"

RESP=$(api GET "/settings")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /settings without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/jobs" "$TOKEN_A")
assert_eq "GET /jobs with auth → returns array" "true" "$(echo "$RESP" | jq 'type == "array"')"

RESP=$(api GET "/jobs")
CODE=$(echo "$RESP" | jq -r '.error.code // empty' 2>/dev/null)
assert_eq "GET /jobs without auth → UNAUTHORIZED" "UNAUTHORIZED" "$CODE"

RESP=$(api GET "/lint/reports" "$TOKEN_A")
assert_eq "GET /lint/reports with auth → returns array" "true" "$(echo "$RESP" | jq 'type == "array"')"

# ===========================================================================
# Test Group 6: WebSocket auth (cannot impersonate via query param)
# ===========================================================================

echo ""
bold "6. WebSocket auth"
echo ""

# We can't do a full WebSocket test from bash, but we can verify the
# endpoint exists and the old query param pattern is gone from the source.
if grep -qF 'query_params.get("user_id")' src/wikimind/api/routes/ws.py 2>/dev/null; then
    assert_eq "WebSocket no longer reads user_id from query params" "gone" "still present"
else
    assert_eq "WebSocket no longer reads user_id from query params" "gone" "gone"
fi

if grep -q 'get_ws_user_id' src/wikimind/api/deps.py 2>/dev/null; then
    assert_eq "get_ws_user_id helper exists in deps.py" "true" "true"
else
    assert_eq "get_ws_user_id helper exists in deps.py" "true" "false"
fi

# ===========================================================================
# Cleanup: delete test sources (as the owning user)
# ===========================================================================

echo ""
bold "Cleanup"
echo ""

api DELETE "/ingest/sources/$SRC_A1_ID" "$TOKEN_A" > /dev/null 2>&1
api DELETE "/ingest/sources/$SRC_A2_ID" "$TOKEN_A" > /dev/null 2>&1
api DELETE "/ingest/sources/$SRC_B1_ID" "$TOKEN_B" > /dev/null 2>&1

# Remove test users
docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U wikimind -d wikimind -q -c "
    DELETE FROM \"user\" WHERE id IN ('${USER_A_ID}', '${USER_B_ID}');
" 2>/dev/null

echo "  Cleaned up test data"

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
