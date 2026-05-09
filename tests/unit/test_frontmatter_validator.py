"""Tests for engine/frontmatter_validator.py."""

from __future__ import annotations

from wikimind.engine.frontmatter_validator import parse_frontmatter, validate_frontmatter


class TestParseFrontmatter:
    def test_valid(self) -> None:
        assert parse_frontmatter("---\ntitle: Hello\nslug: hello\n---\n# Body") is not None

    def test_no_frontmatter(self) -> None:
        assert parse_frontmatter("# Just a heading") is None

    def test_no_closing(self) -> None:
        assert parse_frontmatter("---\ntitle: Hello\n# Body") is None

    def test_malformed_yaml(self) -> None:
        assert parse_frontmatter("---\n: : invalid [\n---\n# Body") is None

    def test_empty(self) -> None:
        assert parse_frontmatter("---\n---\n# Body") is None


class TestValidateFrontmatter:
    def test_valid_source(self) -> None:
        content = "---\npage_type: source\ntitle: T\nslug: t\nsource_id: s1\nsource_type: text\ncompiled: 2025-01-01T00:00:00\n---\n"
        assert validate_frontmatter(content) is True

    def test_valid_concept(self) -> None:
        assert validate_frontmatter("---\npage_type: concept\ntitle: T\nslug: t\nconcept_id: c1\n---\n") is True

    def test_valid_answer(self) -> None:
        assert validate_frontmatter("---\npage_type: answer\ntitle: T\nslug: t\nconversation_id: c1\n---\n") is True

    def test_valid_index(self) -> None:
        assert validate_frontmatter("---\npage_type: index\ntitle: T\nslug: t\nscope: global\n---\n") is True

    def test_valid_meta(self) -> None:
        assert validate_frontmatter("---\npage_type: meta\ntitle: T\nslug: t\n---\n") is True

    def test_no_frontmatter(self) -> None:
        assert validate_frontmatter("# Just a heading") is False

    def test_missing_page_type(self) -> None:
        assert validate_frontmatter("---\ntitle: T\nslug: t\n---\n") is False

    def test_unknown_page_type(self) -> None:
        assert validate_frontmatter("---\npage_type: unknown\ntitle: T\nslug: t\n---\n") is False

    def test_invalid_fields(self) -> None:
        assert validate_frontmatter("---\npage_type: source\ntitle: T\nslug: t\n---\n") is False

    def test_invalid_date(self) -> None:
        assert (
            validate_frontmatter(
                "---\npage_type: source\ntitle: T\nslug: t\nsource_id: s1\nsource_type: text\ncompiled: bad\n---\n"
            )
            is False
        )
