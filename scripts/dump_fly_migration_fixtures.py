"""Dump minimal migration replay fixtures from a live Postgres database.

This avoids a local ``pg_dump`` dependency by introspecting the source database
via asyncpg and writing schema/data SQL files for the migration-replay harness.
"""
# ruff: noqa: D103, PLR0911, PERF401, TC003

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

SUPPORT_TABLES = ["alembic_version", "user", "article"]
MIGRATION_TABLES = [
    "compiled_claim",
    "concept_cluster",
    "claim_concept",
    "compilation_schema",
    "compiledclaim",
    "conceptcluster",
    "claimconcept",
    "compilationschema",
]


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return "'" + value.isoformat(sep=" ") + "'"
    if isinstance(value, UUID):
        return f"'{value}'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"E'\\\\x{bytes(value).hex()}'::bytea"
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


async def table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = $1
            """,
            table,
        )
    )


async def existing_tables(conn: asyncpg.Connection, candidates: Iterable[str]) -> list[str]:
    present: list[str] = []
    for table in candidates:
        if await table_exists(conn, table):
            present.append(table)
    return present


async def fetch_columns(conn: asyncpg.Connection, table: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            a.attname AS column_name,
            pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
            NOT a.attnotnull AS is_nullable,
            pg_get_expr(ad.adbin, ad.adrelid) AS default_expr
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE n.nspname = 'public'
          AND c.relname = $1
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        table,
    )


async def fetch_constraints(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT pg_get_constraintdef(c.oid, true) AS ddl
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = $1
          AND c.contype IN ('p', 'u', 'f', 'c')
        ORDER BY
            CASE c.contype
                WHEN 'p' THEN 1
                WHEN 'u' THEN 2
                WHEN 'f' THEN 3
                WHEN 'c' THEN 4
                ELSE 5
            END,
            c.conname
        """,
        table,
    )
    return [row["ddl"] for row in rows]


async def fetch_indexes(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT pg_get_indexdef(i.indexrelid) AS ddl
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = $1
          AND NOT EXISTS (
              SELECT 1
              FROM pg_constraint c
              WHERE c.conindid = i.indexrelid
          )
        ORDER BY idx.relname
        """,
        table,
    )
    return [row["ddl"] + ";" for row in rows]


async def render_create_table(conn: asyncpg.Connection, table: str) -> str:
    lines: list[str] = []
    for col in await fetch_columns(conn, table):
        line = f"    {quote_ident(col['column_name'])} {col['data_type']}"
        if col["default_expr"] is not None:
            line += f" DEFAULT {col['default_expr']}"
        if not col["is_nullable"]:
            line += " NOT NULL"
        lines.append(line)

    for constraint in await fetch_constraints(conn, table):
        lines.append(f"    {constraint}")

    body = ",\n".join(lines)
    return f"CREATE TABLE {quote_ident(table)} (\n{body}\n);"


async def render_inserts(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(f"SELECT * FROM {quote_ident(table)}")
    if not rows:
        return []

    columns = rows[0].keys()
    col_sql = ", ".join(quote_ident(col) for col in columns)
    inserts: list[str] = []
    for row in rows:
        values = ", ".join(sql_literal(row[col]) for col in columns)
        inserts.append(f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({values});")
    return inserts


async def dump(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
    )
    try:
        tables = await existing_tables(conn, SUPPORT_TABLES + MIGRATION_TABLES)
        if "alembic_version" not in tables:
            raise RuntimeError("source database is missing alembic_version")

        schema_chunks: list[str] = []
        data_chunks: list[str] = []
        for table in tables:
            schema_chunks.append(await render_create_table(conn, table))
            schema_chunks.extend(await fetch_indexes(conn, table))
            data_chunks.extend(await render_inserts(conn, table))

        Path(args.schema_sql).write_text("\n\n".join(schema_chunks) + "\n", encoding="utf-8")
        Path(args.data_sql).write_text("\n".join(data_chunks) + "\n", encoding="utf-8")
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--schema-sql", required=True)
    parser.add_argument("--data-sql", required=True)
    return parser.parse_args()


def main() -> None:
    asyncio.run(dump(parse_args()))


if __name__ == "__main__":
    main()
