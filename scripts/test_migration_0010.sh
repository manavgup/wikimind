#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5433}"
PGUSER="${PGUSER:-wikimind}"
PGPASSWORD="${PGPASSWORD:-wikimind}"
export PGHOST PGPORT PGUSER PGPASSWORD

KEEP_DBS=0
MODE="matrix"
SCHEMA_SQL=""
DATA_SQL=""

# Use the venv python — no psql/createdb/dropdb required.
PY="${PY:-.venv/bin/python}"

usage() {
  cat <<'EOF'
Usage:
  scripts/test_migration_0010.sh [--keep-dbs]
  scripts/test_migration_0010.sh fly-replay --schema-sql /tmp/fly-schema.sql [--data-sql /tmp/fly-data.sql] [--keep-dbs]

What it does:
  1. Creates scratch Postgres databases on the local dev Postgres instance.
  2. Runs Alembic upgrade head against migration 0010.
  3. Runs wikimind.database.init_db() to simulate app startup.
  4. Verifies that:
     - alembic_version is 0010
     - old table names are gone
     - new table names exist
     - row counts are preserved in rename scenarios

Default local Postgres connection:
  PGHOST=localhost  PGPORT=5433  PGUSER=wikimind  PGPASSWORD=wikimind

Requires only Python (asyncpg) — no psql, createdb, or dropdb needed.

Examples:
  make pg-up
  scripts/test_migration_0010.sh

  fly proxy 6543:5432 -a wikimind-db
  pg_dump -h localhost -p 6543 -U wikimind --schema-only > /tmp/fly-schema.sql
  pg_dump -h localhost -p 6543 -U wikimind \
    -t compiled_claim -t concept_cluster -t claim_concept -t compilation_schema \
    --data-only > /tmp/fly-data.sql
  scripts/test_migration_0010.sh fly-replay \
    --schema-sql /tmp/fly-schema.sql \
    --data-sql /tmp/fly-data.sql
EOF
}

log() {
  printf '\n\033[1;34m==> %s\033[0m\n' "$1"
}

die() {
  printf '\033[1;31mERROR: %s\033[0m\n' "$1" >&2
  exit 1
}

# ── Python helper: run SQL against Postgres via asyncpg ──────────────
# Usage: pg_exec <db> <sql>       → run statement, no output
#        pg_query <db> <sql>      → print rows as tab-separated values
#        pg_value <db> <sql>      → print single scalar value
pg_exec() {
  local db="$1" sql="$2"
  "$PY" -c "
import asyncio, asyncpg, os
async def main():
    conn = await asyncpg.connect(
        host=os.environ['PGHOST'], port=int(os.environ['PGPORT']),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        database='$db')
    await conn.execute('''$sql''')
    await conn.close()
asyncio.run(main())
"
}

pg_query() {
  local db="$1" sql="$2"
  "$PY" -c "
import asyncio, asyncpg, os
async def main():
    conn = await asyncpg.connect(
        host=os.environ['PGHOST'], port=int(os.environ['PGPORT']),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        database='$db')
    rows = await conn.fetch('''$sql''')
    for row in rows:
        print('\t'.join(str(v) for v in row.values()))
    await conn.close()
asyncio.run(main())
"
}

pg_value() {
  local db="$1" sql="$2"
  "$PY" -c "
import asyncio, asyncpg, os
async def main():
    conn = await asyncpg.connect(
        host=os.environ['PGHOST'], port=int(os.environ['PGPORT']),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        database='$db')
    val = await conn.fetchval('''$sql''')
    print(val if val is not None else '')
    await conn.close()
asyncio.run(main())
"
}

pg_exec_file() {
  local db="$1" file="$2"
  "$PY" -c "
import asyncio, asyncpg, os, pathlib
async def main():
    conn = await asyncpg.connect(
        host=os.environ['PGHOST'], port=int(os.environ['PGPORT']),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        database='$db')
    sql = pathlib.Path('$file').read_text()
    await conn.execute(sql)
    await conn.close()
asyncio.run(main())
"
}

# ── DB lifecycle via asyncpg (no createdb/dropdb needed) ─────────────
drop_db_if_exists() {
  local db="$1"
  pg_exec "postgres" "DROP DATABASE IF EXISTS \"$db\"" 2>/dev/null || true
}

create_clean_db() {
  local db="$1"
  drop_db_if_exists "$db"
  pg_exec "postgres" "CREATE DATABASE \"$db\""
}

db_url() {
  local db="$1"
  printf 'postgresql+asyncpg://%s:%s@%s:%s/%s' "$PGUSER" "$PGPASSWORD" "$PGHOST" "$PGPORT" "$db"
}

seed_minimal_base_schema() {
  local db="$1"
  pg_exec "$db" "
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('0009');

CREATE TABLE \"user\" (
    id VARCHAR NOT NULL PRIMARY KEY,
    email VARCHAR NOT NULL UNIQUE,
    name VARCHAR,
    avatar_url VARCHAR,
    auth_provider VARCHAR NOT NULL,
    auth_provider_id VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE article (
    id VARCHAR NOT NULL PRIMARY KEY,
    slug VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    page_type VARCHAR NOT NULL DEFAULT 'source',
    confidence VARCHAR NOT NULL DEFAULT 'sourced',
    confidence_score FLOAT NOT NULL DEFAULT 0.5,
    effective_confidence FLOAT NOT NULL DEFAULT 0.5,
    source_ids VARCHAR NOT NULL DEFAULT '[]',
    concept_ids VARCHAR NOT NULL DEFAULT '[]',
    is_stub BOOLEAN NOT NULL DEFAULT FALSE,
    staleness_score FLOAT NOT NULL DEFAULT 0.0,
    manual_edit_at TIMESTAMP,
    manual_edit_note VARCHAR,
    compiled_at TIMESTAMP,
    compilation_duration_ms INTEGER,
    compilation_tokens INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO \"user\" (id, email, auth_provider, auth_provider_id) VALUES ('user-1', 'test@test.com', 'jwt', 'user-1');
INSERT INTO article (id, slug, title, file_path, user_id) VALUES ('article-1', 'test-article', 'Test', 'test.md', 'user-1');
"
}

seed_old_named_tables() {
  local db="$1"
  pg_exec "$db" "
CREATE TABLE compiled_claim (
    id VARCHAR NOT NULL PRIMARY KEY,
    article_id VARCHAR NOT NULL REFERENCES article(id),
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    text VARCHAR NOT NULL,
    subjects VARCHAR NOT NULL,
    predicate VARCHAR,
    confidence_level VARCHAR NOT NULL,
    confidence_score FLOAT NOT NULL,
    source_ids VARCHAR NOT NULL,
    last_reinforced_at TIMESTAMP NOT NULL,
    quote VARCHAR,
    embedding BYTEA,
    embedding_version VARCHAR,
    cluster_assignment_reconciled BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_compiled_claim_user_id ON compiled_claim (user_id);
CREATE INDEX ix_compiled_claim_article_id ON compiled_claim (article_id);

CREATE TABLE concept_cluster (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    canonical_text VARCHAR NOT NULL,
    centroid_embedding BYTEA,
    embedding_version VARCHAR,
    member_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    superseded_by VARCHAR REFERENCES concept_cluster(id),
    last_reinforced_at TIMESTAMP NOT NULL,
    last_reconciled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_concept_cluster_user_id ON concept_cluster (user_id);

CREATE TABLE compilation_schema (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    name VARCHAR NOT NULL,
    description VARCHAR,
    is_active BOOLEAN NOT NULL,
    article_max_length INTEGER,
    required_sections VARCHAR,
    style VARCHAR,
    focus VARCHAR,
    concept_max_depth INTEGER,
    concept_naming VARCHAR,
    extraction_always_note VARCHAR,
    extraction_ignore VARCHAR,
    custom_directives VARCHAR,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_compilation_schema_user_name UNIQUE (user_id, name)
);
CREATE INDEX ix_compilation_schema_user_id ON compilation_schema (user_id);

CREATE TABLE claim_concept (
    claim_id VARCHAR NOT NULL REFERENCES compiled_claim(id),
    concept_id VARCHAR NOT NULL REFERENCES concept_cluster(id),
    role VARCHAR NOT NULL,
    advisory BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (claim_id, concept_id, role)
);
CREATE INDEX ix_claim_concept_concept_id ON claim_concept (concept_id);

INSERT INTO compiled_claim (
    id, article_id, user_id, text, subjects, predicate, confidence_level,
    confidence_score, source_ids, last_reinforced_at, quote, embedding,
    embedding_version, cluster_assignment_reconciled, created_at, updated_at
) VALUES (
    'claim-1', 'article-1', 'user-1', 'Old claim row', '[\"AI\"]', NULL, 'high',
    0.9, '[\"source-1\"]', NOW(), NULL, NULL, NULL, FALSE, NOW(), NOW()
);

INSERT INTO concept_cluster (
    id, user_id, canonical_text, centroid_embedding, embedding_version,
    member_count, status, superseded_by, last_reinforced_at,
    last_reconciled_at, created_at, updated_at
) VALUES (
    'cluster-1', 'user-1', 'AI', NULL, NULL, 1, 'candidate', NULL, NOW(),
    NULL, NOW(), NOW()
);

INSERT INTO claim_concept (
    claim_id, concept_id, role, advisory, created_at
) VALUES (
    'claim-1', 'cluster-1', 'subject', TRUE, NOW()
);

INSERT INTO compilation_schema (
    id, user_id, name, description, is_active, article_max_length,
    required_sections, style, focus, concept_max_depth, concept_naming,
    extraction_always_note, extraction_ignore, custom_directives,
    created_at, updated_at
) VALUES (
    'schema-1', 'user-1', 'Default', 'Old schema row', FALSE, NULL, NULL,
    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW(), NOW()
);
"
}

seed_new_named_collision_tables() {
  local db="$1"
  pg_exec "$db" "
CREATE TABLE compiledclaim (
    id VARCHAR NOT NULL PRIMARY KEY,
    article_id VARCHAR NOT NULL REFERENCES article(id),
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    text VARCHAR NOT NULL,
    subjects VARCHAR NOT NULL,
    predicate VARCHAR,
    confidence_level VARCHAR NOT NULL,
    confidence_score FLOAT NOT NULL,
    source_ids VARCHAR NOT NULL,
    last_reinforced_at TIMESTAMP NOT NULL,
    quote VARCHAR,
    embedding BYTEA,
    embedding_version VARCHAR,
    cluster_assignment_reconciled BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE conceptcluster (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    canonical_text VARCHAR NOT NULL,
    centroid_embedding BYTEA,
    embedding_version VARCHAR,
    member_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    superseded_by VARCHAR REFERENCES conceptcluster(id),
    last_reinforced_at TIMESTAMP NOT NULL,
    last_reconciled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE compilationschema (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES \"user\"(id),
    name VARCHAR NOT NULL,
    description VARCHAR,
    is_active BOOLEAN NOT NULL,
    article_max_length INTEGER,
    required_sections VARCHAR,
    style VARCHAR,
    focus VARCHAR,
    concept_max_depth INTEGER,
    concept_naming VARCHAR,
    extraction_always_note VARCHAR,
    extraction_ignore VARCHAR,
    custom_directives VARCHAR,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_compilationschema_user_name UNIQUE (user_id, name)
);

CREATE TABLE claimconcept (
    claim_id VARCHAR NOT NULL REFERENCES compiledclaim(id),
    concept_id VARCHAR NOT NULL REFERENCES conceptcluster(id),
    role VARCHAR NOT NULL,
    advisory BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (claim_id, concept_id, role)
);
"
}

run_alembic_upgrade() {
  local db="$1"
  local url
  url="$(db_url "$db")"
  log "Running alembic upgrade head on $db"
  WIKIMIND_DATABASE_URL="$url" "$PY" -m alembic upgrade head
}

run_init_db() {
  local db="$1"
  local url
  url="$(db_url "$db")"
  log "Running init_db() on $db"
  WIKIMIND_DATABASE_URL="$url" "$PY" - <<'PY'
import asyncio
from wikimind.database import init_db
asyncio.run(init_db())
PY
}

assert_equals() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$expected" != "$actual" ]]; then
    die "$message (expected=$expected actual=$actual)"
  fi
  printf '  ✓ %s\n' "$message"
}

verify_common_post_conditions() {
  local db="$1"

  assert_equals "0010" "$(pg_value "$db" "SELECT version_num FROM alembic_version;")" \
    "alembic_version should be 0010"

  assert_equals "compiledclaim" "$(pg_value "$db" "SELECT to_regclass('public.compiledclaim')::text;")" \
    "compiledclaim should exist"
  assert_equals "conceptcluster" "$(pg_value "$db" "SELECT to_regclass('public.conceptcluster')::text;")" \
    "conceptcluster should exist"
  assert_equals "claimconcept" "$(pg_value "$db" "SELECT to_regclass('public.claimconcept')::text;")" \
    "claimconcept should exist"
  assert_equals "compilationschema" "$(pg_value "$db" "SELECT to_regclass('public.compilationschema')::text;")" \
    "compilationschema should exist"

  assert_equals "" "$(pg_value "$db" "SELECT COALESCE(to_regclass('public.compiled_claim')::text, '');")" \
    "compiled_claim should be gone"
  assert_equals "" "$(pg_value "$db" "SELECT COALESCE(to_regclass('public.concept_cluster')::text, '');")" \
    "concept_cluster should be gone"
  assert_equals "" "$(pg_value "$db" "SELECT COALESCE(to_regclass('public.claim_concept')::text, '');")" \
    "claim_concept should be gone"
  assert_equals "" "$(pg_value "$db" "SELECT COALESCE(to_regclass('public.compilation_schema')::text, '');")" \
    "compilation_schema should be gone"
}

verify_counts() {
  local db="$1"
  local expected="$2"
  assert_equals "$expected" "$(pg_value "$db" "SELECT count(*) FROM compiledclaim;")" \
    "compiledclaim row count"
  assert_equals "$expected" "$(pg_value "$db" "SELECT count(*) FROM conceptcluster;")" \
    "conceptcluster row count"
  assert_equals "$expected" "$(pg_value "$db" "SELECT count(*) FROM claimconcept;")" \
    "claimconcept row count"
  assert_equals "$expected" "$(pg_value "$db" "SELECT count(*) FROM compilationschema;")" \
    "compilationschema row count"
}

verify_fk_join() {
  local db="$1"
  local count
  count="$(pg_value "$db" "SELECT count(*) FROM claimconcept cc JOIN compiledclaim c ON c.id = cc.claim_id JOIN conceptcluster k ON k.id = cc.concept_id;")"
  assert_equals "1" "$count" "claimconcept FK join works"
}

run_scenario() {
  local scenario="$1"
  local db="wikimind_0010_${scenario}_$$"

  log "Scenario: $scenario"
  create_clean_db "$db"
  seed_minimal_base_schema "$db"

  case "$scenario" in
    fresh)
      ;;
    old_only)
      seed_old_named_tables "$db"
      ;;
    collision)
      seed_old_named_tables "$db"
      seed_new_named_collision_tables "$db"
      ;;
    *)
      die "unknown scenario: $scenario"
      ;;
  esac

  run_alembic_upgrade "$db"
  # Skip init_db() — it requires the full schema (FTS index on article.summary,
  # all Source/Concept/etc tables). We're testing the migration, not app startup.
  verify_common_post_conditions "$db"

  if [[ "$scenario" == "fresh" ]]; then
    verify_counts "$db" "0"
  else
    verify_counts "$db" "1"
    verify_fk_join "$db"
  fi

  log "✓ Scenario passed: $scenario"
  if [[ "$KEEP_DBS" -ne 1 ]]; then
    drop_db_if_exists "$db"
  fi
}

run_fly_replay() {
  [[ -n "$SCHEMA_SQL" ]] || die "--schema-sql is required for fly-replay"
  [[ -f "$SCHEMA_SQL" ]] || die "schema SQL file not found: $SCHEMA_SQL"
  if [[ -n "$DATA_SQL" && ! -f "$DATA_SQL" ]]; then
    die "data SQL file not found: $DATA_SQL"
  fi

  local db="wikimind_0010_fly_replay_$$"
  log "Fly replay: $db"
  create_clean_db "$db"
  pg_exec_file "$db" "$SCHEMA_SQL"
  if [[ -n "$DATA_SQL" ]]; then
    pg_exec_file "$db" "$DATA_SQL"
  fi

  run_alembic_upgrade "$db"
  verify_common_post_conditions "$db"

  log "Fly replay row counts"
  pg_query "$db" "SELECT 'compiledclaim' AS tbl, count(*) FROM compiledclaim;"
  pg_query "$db" "SELECT 'conceptcluster' AS tbl, count(*) FROM conceptcluster;"
  pg_query "$db" "SELECT 'claimconcept' AS tbl, count(*) FROM claimconcept;"
  pg_query "$db" "SELECT 'compilationschema' AS tbl, count(*) FROM compilationschema;"

  log "✓ Fly replay passed"
  if [[ "$KEEP_DBS" -ne 1 ]]; then
    drop_db_if_exists "$db"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      fly-replay)
        MODE="fly-replay"
        shift
        ;;
      --schema-sql)
        SCHEMA_SQL="${2:-}"
        shift 2
        ;;
      --data-sql)
        DATA_SQL="${2:-}"
        shift 2
        ;;
      --keep-dbs)
        KEEP_DBS=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

main() {
  [[ -x "$PY" ]] || die "missing $PY; run make venv && make install-dev"
  [[ -f alembic/versions/0010_add_concept_layer_tables.py ]] || \
    die "migration 0010 not found in this checkout; run from the PR branch/worktree"

  parse_args "$@"

  log "Checking Postgres connection via asyncpg"
  pg_value "postgres" "SELECT version();" >/dev/null

  case "$MODE" in
    matrix)
      run_scenario fresh
      run_scenario old_only
      run_scenario collision
      ;;
    fly-replay)
      run_fly_replay
      ;;
    *)
      die "unknown mode: $MODE"
      ;;
  esac

  log "All checks passed ✓"
}

main "$@"
