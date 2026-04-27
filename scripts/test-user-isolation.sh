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
    echo "  WARNING:  Auth may not be enabled — tests may not be meaningful"
fi

# ===========================================================================
# Setup: Create test users via database
# ===========================================================================

echo ""
bold "Setup: Creating test users"
echo ""

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

info "Created User A: $USER_A_ID"
info "Created User B: $USER_B_ID"

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
# Test Group 2: Source ingestion and ownership
# ===========================================================================

echo ""
bold "2. Source ingestion and ownership"
echo ""

# -- User A ingests two sources --

SRC_A1=$(api POST "/ingest/text" "$TOKEN_A" \
    '{"content":"User A secret document number one with sensitive data","title":"A-Doc-1","auto_compile":false}')
SRC_A1_ID=$(echo "$SRC_A1" | jq -r '.id')
SRC_A1_UID=$(echo "$SRC_A1" | jq -r '.user_id')
assert_eq "Ingest source 1 as User A → user_id matches" "$USER_A_ID" "$SRC_A1_UID"
info "Source A1: id=$SRC_A1_ID  user_id=$SRC_A1_UID  title=$(echo "$SRC_A1" | jq -r '.title')"

SRC_A2=$(api POST "/ingest/text" "$TOKEN_A" \
    '{"content":"User A second document with more private info","title":"A-Doc-2","auto_compile":false}')
SRC_A2_ID=$(echo "$SRC_A2" | jq -r '.id')
SRC_A2_UID=$(echo "$SRC_A2" | jq -r '.user_id')
assert_eq "Ingest source 2 as User A → user_id matches" "$USER_A_ID" "$SRC_A2_UID"
info "Source A2: id=$SRC_A2_ID  user_id=$SRC_A2_UID  title=$(echo "$SRC_A2" | jq -r '.title')"

# -- User B ingests one source --

SRC_B1=$(api POST "/ingest/text" "$TOKEN_B" \
    '{"content":"User B private note that A should never see","title":"B-Doc-1","auto_compile":false}')
SRC_B1_ID=$(echo "$SRC_B1" | jq -r '.id')
SRC_B1_UID=$(echo "$SRC_B1" | jq -r '.user_id')
assert_eq "Ingest source 1 as User B → user_id matches" "$USER_B_ID" "$SRC_B1_UID"
info "Source B1: id=$SRC_B1_ID  user_id=$SRC_B1_UID  title=$(echo "$SRC_B1" | jq -r '.title')"

# ===========================================================================
# Test Group 3: Source list isolation
# ===========================================================================

echo ""
bold "3. Source list isolation"
echo ""

A_SOURCES=$(api GET "/ingest/sources" "$TOKEN_A")
A_COUNT=$(echo "$A_SOURCES" | jq 'length')
assert_eq "User A sees exactly 2 sources" "2" "$A_COUNT"
info "User A sources: $(echo "$A_SOURCES" | jq -c '[.[] | {id: .id, title: .title}]')"

B_SOURCES=$(api GET "/ingest/sources" "$TOKEN_B")
B_COUNT=$(echo "$B_SOURCES" | jq 'length')
assert_eq "User B sees exactly 1 source" "1" "$B_COUNT"
info "User B sources: $(echo "$B_SOURCES" | jq -c '[.[] | {id: .id, title: .title}]')"

# ===========================================================================
# Test Group 4: Cross-user source access is blocked
# ===========================================================================

echo ""
bold "4. Cross-user source access is blocked"
echo ""

# User A tries to read User B's source
RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_A")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User A GET User B's source ($SRC_B1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

# User B tries to read User A's source
RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B GET User A's source ($SRC_A1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

# User A can read their OWN source
RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User A GET own source ($SRC_A1_ID) → A-Doc-1" "A-Doc-1" "$TITLE"
info "Response: id=$(echo "$RESP" | jq -r '.id')  title=$TITLE  user_id=$(echo "$RESP" | jq -r '.user_id')"

# User B can read their OWN source
RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_B")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User B GET own source ($SRC_B1_ID) → B-Doc-1" "B-Doc-1" "$TITLE"
info "Response: id=$(echo "$RESP" | jq -r '.id')  title=$TITLE  user_id=$(echo "$RESP" | jq -r '.user_id')"

# ===========================================================================
# Test Group 5: Cross-user deletion is blocked
# ===========================================================================

echo ""
bold "5. Cross-user deletion is blocked"
echo ""

# User B tries to delete User A's source
RESP=$(api DELETE "/ingest/sources/$SRC_A1_ID" "$TOKEN_B")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User B DELETE User A's source ($SRC_A1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

# Verify User A's source still exists
RESP=$(api GET "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User A's source survives User B's delete attempt" "A-Doc-1" "$TITLE"
info "Source still exists: id=$SRC_A1_ID  title=$TITLE"

# User A tries to delete User B's source
RESP=$(api DELETE "/ingest/sources/$SRC_B1_ID" "$TOKEN_A")
DETAIL=$(echo "$RESP" | jq -r '.detail // empty')
assert_eq "User A DELETE User B's source ($SRC_B1_ID) → 404" "Source not found" "$DETAIL"
info "Response: $(echo "$RESP" | jq -c .)"

# Verify User B's source still exists
RESP=$(api GET "/ingest/sources/$SRC_B1_ID" "$TOKEN_B")
TITLE=$(echo "$RESP" | jq -r '.title')
assert_eq "User B's source survives User A's delete attempt" "B-Doc-1" "$TITLE"
info "Source still exists: id=$SRC_B1_ID  title=$TITLE"

# ===========================================================================
# Test Group 6: Article isolation
# ===========================================================================

echo ""
bold "6. Article isolation"
echo ""

A_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_A")
A_ART_COUNT=$(echo "$A_ARTICLES" | jq 'length')
info "User A article count: $A_ART_COUNT"

B_ARTICLES=$(api GET "/wiki/articles" "$TOKEN_B")
B_ART_COUNT=$(echo "$B_ARTICLES" | jq 'length')
assert_eq "User B sees 0 of User A's articles" "0" "$B_ART_COUNT"
info "User B article count: $B_ART_COUNT"

# ===========================================================================
# Test Group 7: Conversation isolation
# ===========================================================================

echo ""
bold "7. Conversation isolation"
echo ""

A_CONVOS=$(api GET "/query/conversations" "$TOKEN_A")
A_CONV_COUNT=$(echo "$A_CONVOS" | jq 'length')
info "User A conversation count: $A_CONV_COUNT"

B_CONVOS=$(api GET "/query/conversations" "$TOKEN_B")
B_CONV_COUNT=$(echo "$B_CONVOS" | jq 'length')
assert_eq "User B sees 0 of User A's conversations" "0" "$B_CONV_COUNT"
info "User B conversation count: $B_CONV_COUNT"

# ===========================================================================
# Test Group 8: Protected endpoints require auth
# ===========================================================================

echo ""
bold "8. Protected endpoints require auth"
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
# Test Group 9: WebSocket auth (source code verification)
# ===========================================================================

echo ""
bold "9. WebSocket auth (source code verification)"
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
# Cleanup: delete test data via API, then remove users from DB
# ===========================================================================

echo ""
bold "Cleanup"
echo ""

# Delete sources via API (as the owning user)
RESP=$(api DELETE "/ingest/sources/$SRC_A1_ID" "$TOKEN_A")
info "Deleted source A1 ($SRC_A1_ID): $(echo "$RESP" | jq -c .)"

RESP=$(api DELETE "/ingest/sources/$SRC_A2_ID" "$TOKEN_A")
info "Deleted source A2 ($SRC_A2_ID): $(echo "$RESP" | jq -c .)"

RESP=$(api DELETE "/ingest/sources/$SRC_B1_ID" "$TOKEN_B")
info "Deleted source B1 ($SRC_B1_ID): $(echo "$RESP" | jq -c .)"

# Verify sources are gone
A_FINAL=$(api GET "/ingest/sources" "$TOKEN_A" | jq 'length')
B_FINAL=$(api GET "/ingest/sources" "$TOKEN_B" | jq 'length')
info "User A remaining sources: $A_FINAL"
info "User B remaining sources: $B_FINAL"

# Remove test users from database
docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U wikimind -d wikimind -q -c "
    DELETE FROM \"user\" WHERE id IN ('${USER_A_ID}', '${USER_B_ID}');
" 2>/dev/null
info "Deleted User A ($USER_A_ID) from database"
info "Deleted User B ($USER_B_ID) from database"

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
