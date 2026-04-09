"""Tests for the append-only wiki/log.md activity log."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from wikimind.services.activity_log import _LOG_HEADER, append_log_entry


class TestAppendLogEntry:
    """Unit tests for append_log_entry."""

    def test_creates_log_file_with_header_if_missing(self, tmp_path: Path) -> None:
        """First call should create log.md with the standard header."""
        wiki_dir = tmp_path / "wiki"
        # wiki_dir intentionally not pre-created — the function should mkdir.
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("ingest", "Test Source")

        log_path = wiki_dir / "log.md"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert content.startswith(_LOG_HEADER)

    def test_entries_are_appended_not_overwritten(self, tmp_path: Path) -> None:
        """Multiple calls should all appear in the file in order."""
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("ingest", "First")
            append_log_entry("compile", "Second")
            append_log_entry("query", "Third")

        content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "ingest | First" in content
        assert "compile | Second" in content
        assert "query | Third" in content
        # Verify ordering: First appears before Second appears before Third
        assert content.index("First") < content.index("Second") < content.index("Third")

    def test_line_format(self, tmp_path: Path) -> None:
        """Entry should follow ## [YYYY-MM-DD] op | title format."""
        with (
            patch("wikimind.services.activity_log.get_settings") as mock_settings,
            patch("wikimind.services.activity_log.utcnow_naive") as mock_now,
        ):
            mock_settings.return_value.data_dir = str(tmp_path)
            mock_now.return_value = datetime(2026, 4, 9, 12, 0, 0)
            append_log_entry("ingest", "My Article")

        content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "## [2026-04-09] ingest | My Article\n" in content

    def test_extra_dict_produces_detail_lines(self, tmp_path: Path) -> None:
        """When extra is provided, indented key: value lines should follow the heading."""
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry(
                "ingest",
                "Test",
                extra={"source_type": "url", "source_url": "https://example.com"},
            )

        content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "- source_type: url\n" in content
        assert "- source_url: https://example.com\n" in content

    def test_extra_none_produces_no_detail_lines(self, tmp_path: Path) -> None:
        """When extra is None, no detail lines should appear."""
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("query", "What is X?")

        content = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        # Only header line, blank, heading line, blank — no "- key:" lines
        detail_lines = [ln for ln in lines if ln.startswith("- ")]
        assert detail_lines == []

    def test_preserves_existing_content(self, tmp_path: Path) -> None:
        """Appending should preserve the header and all prior entries."""
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir(parents=True)
        log_path = wiki_dir / "log.md"
        log_path.write_text(_LOG_HEADER + "## [2026-01-01] old | entry\n\n", encoding="utf-8")

        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("compile", "New Article")

        content = log_path.read_text(encoding="utf-8")
        assert "## [2026-01-01] old | entry" in content
        assert "compile | New Article" in content
