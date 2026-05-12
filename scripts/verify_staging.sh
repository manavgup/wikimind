#!/usr/bin/env bash
# verify_staging.sh — Run after deploying to prove staging works
# Usage: ./scripts/verify_staging.sh
# Captures logs, API responses, and screenshots for evidence

set -euo pipefail

BASE="https://wikimind-staging.fly.dev"
APP="wikimind-staging"
EVIDENCE_DIR="docs/evidence/staging-verification"
mkdir -p "$EVIDENCE_DIR"

echo "=========================================="
echo " WikiMind Staging Verification"
echo " $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="
echo ""

# 1. App status
echo "--- 1. Fly.io App Status ---"
flyctl status -a "$APP" | tee "$EVIDENCE_DIR/fly-status.txt"
echo ""

# 2. Secrets check (no values, just names)
echo "--- 2. Required Secrets Present ---"
SECRETS=$(flyctl secrets list -a "$APP" 2>&1)
for secret in DATABASE_URL WIKIMIND_REDIS_URL ANTHROPIC_API_KEY WIKIMIND_AUTH__JWT_SECRET_KEY; do
  if echo "$SECRETS" | grep -q "$secret"; then
    echo "  [OK] $secret"
  else
    echo "  [MISSING] $secret"
  fi
done | tee "$EVIDENCE_DIR/secrets-check.txt"
echo ""

# 3. Health endpoint
echo "--- 3. Health Check ---"
HEALTH=$(curl -sf --max-time 10 "$BASE/health" 2>&1) && {
  echo "$HEALTH" | python3 -m json.tool | tee "$EVIDENCE_DIR/health.json"
} || {
  echo "  [FAIL] /health not responding"
  echo "FAIL" > "$EVIDENCE_DIR/health.json"
}
echo ""

# 4. Deep health (after PR #550 is merged)
echo "--- 4. Deep Health Check ---"
DEEP=$(curl -sf --max-time 10 "$BASE/health/deep" 2>&1) && {
  echo "$DEEP" | python3 -m json.tool | tee "$EVIDENCE_DIR/health-deep.json"
} || {
  echo "  [SKIP] /health/deep not available (PR #550 not deployed yet)"
}
echo ""

# 5. Background mode check
echo "--- 5. Background Mode ---"
if echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('background_mode','unknown'))" 2>/dev/null; then
  MODE=$(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('background_mode','unknown'))")
  if [ "$MODE" = "arq" ]; then
    echo "  [OK] background_mode=arq (Redis working)"
  else
    echo "  [WARN] background_mode=$MODE (expected arq)"
  fi
else
  echo "  [SKIP] background_mode field not present (PR #561 not deployed)"
fi | tee "$EVIDENCE_DIR/background-mode.txt"
echo ""

# 6. Recent logs (check for startup errors)
echo "--- 6. Recent Startup Logs ---"
flyctl logs -a "$APP" --no-tail 2>&1 | grep -E "migration|error|mode=|Production|Redis|WARNING" | tail -20 | tee "$EVIDENCE_DIR/startup-logs.txt"
echo ""

# 7. API functional check (requires auth token)
echo "--- 7. API Functional Check ---"
if [ -n "${STAGING_TOKEN:-}" ]; then
  # Articles list
  ARTICLES=$(curl -sf --max-time 10 "$BASE/api/wiki/articles" -H "Authorization: Bearer $STAGING_TOKEN" 2>&1)
  echo "  Articles endpoint: $(echo "$ARTICLES" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} articles')" 2>/dev/null || echo "error")"

  # Sources list
  SOURCES=$(curl -sf --max-time 10 "$BASE/api/ingest/sources" -H "Authorization: Bearer $STAGING_TOKEN" 2>&1)
  echo "  Sources endpoint: $(echo "$SOURCES" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} sources')" 2>/dev/null || echo "error")"

  # Admin stats (after PR #551)
  STATS=$(curl -sf --max-time 10 "$BASE/api/admin/stats" -H "Authorization: Bearer $STAGING_TOKEN" 2>&1)
  echo "  Admin stats: $(echo "$STATS" | python3 -m json.tool 2>/dev/null || echo "not available")"
else
  echo "  [SKIP] Set STAGING_TOKEN env var to test authenticated endpoints"
fi | tee "$EVIDENCE_DIR/api-check.txt"
echo ""

# 8. Summary
echo "=========================================="
echo " VERIFICATION COMPLETE"
echo " Evidence saved to: $EVIDENCE_DIR/"
echo "=========================================="
ls -la "$EVIDENCE_DIR/"
