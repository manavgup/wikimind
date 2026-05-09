"""Tests for database.py helper functions."""

from __future__ import annotations

import pytest

from wikimind.database import (
    _collect_concept_names,
    _create_engine_from_url,
    _parse_concept_names_from_json,
    _parse_ssl,
)


class TestParseConceptNames:
    def test_valid(self):
        assert "machine-learning" in _parse_concept_names_from_json('["Machine Learning"]')

    def test_empty(self):
        assert _parse_concept_names_from_json("[]") == []

    def test_invalid(self):
        assert _parse_concept_names_from_json("bad") == []

    def test_none(self):
        assert _parse_concept_names_from_json(None) == []

    def test_not_list(self):
        assert _parse_concept_names_from_json('{"k": "v"}') == []


class TestCollectConceptNames:
    def test_empty(self):
        assert _collect_concept_names([]) == ({}, [])

    def test_single(self):
        names, concepts = _collect_concept_names([("a1", '["ML"]')])
        assert "ml" in names

    def test_invalid(self):
        names, concepts = _collect_concept_names([("a1", "bad")])
        assert names == {}


class TestParseSsl:
    def test_no_ssl(self):
        url, args = _parse_ssl("postgresql://localhost/db")
        assert args == {}

    def test_require(self):
        _url, args = _parse_ssl("postgresql://localhost/db?sslmode=require")
        assert args["ssl"] is True

    def test_disable(self):
        _url, args = _parse_ssl("postgresql://localhost/db?sslmode=disable")
        assert args["ssl"] is False


class TestCreateEngine:
    def test_sqlite(self):
        assert _create_engine_from_url("sqlite+aiosqlite://") is not None

    def test_unsupported(self):
        with pytest.raises(ValueError):
            _create_engine_from_url("mysql://localhost/db")
