"""Tests for the WikiMind CLI commands.

Uses click's CliRunner to test each command in isolation without a live server.
HTTP calls are mocked via monkeypatch on httpx.Client.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from wikimind.cli.client import clear_token, load_token, save_token
from wikimind.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_token(tmp_path, monkeypatch):
    """Redirect TOKEN_PATH to a temp dir so tests don't touch ~/.wikimind/."""
    token_file = tmp_path / "token"
    monkeypatch.setattr("wikimind.cli.client.TOKEN_PATH", token_file)
    return token_file


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


# ---- Top-level ----


def test_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "WikiMind" in result.output
    assert "wiki" in result.output
    assert "ingest" in result.output
    assert "ask" in result.output
    assert "status" in result.output


def test_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# ---- Auth ----


def test_login_success(runner, tmp_token):
    magic_resp = _mock_response(json_data={"dev_token": "magic-tok-123", "status": "ok"})
    verify_resp = _mock_response(
        json_data={
            "access_token": "jwt-abc-123",
            "user": {"id": "u1", "email": "dev@test.com", "name": "Dev"},
        }
    )

    call_count = {"n": 0}

    def mock_post(url, **kwargs):
        call_count["n"] += 1
        if "/magic-link/verify" in url:
            return verify_resp
        return magic_resp

    with patch("wikimind.cli.auth.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.post = mock_post
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["login", "--email", "dev@test.com"])

    assert result.exit_code == 0
    assert "Logged in as Dev" in result.output
    assert tmp_token.read_text().strip() == "jwt-abc-123"


def test_logout(runner, tmp_token):
    tmp_token.write_text("some-token\n")

    result = runner.invoke(cli, ["logout"])
    assert result.exit_code == 0
    assert "Logged out" in result.output
    assert not tmp_token.exists()


def test_logout_not_logged_in(runner, tmp_token):
    result = runner.invoke(cli, ["logout"])
    assert result.exit_code == 0
    assert "Not logged in" in result.output


def test_whoami(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(json_data={"id": "u1", "email": "dev@test.com", "name": "Dev"})

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["whoami"])

    assert result.exit_code == 0
    assert "Dev" in result.output
    assert "dev@test.com" in result.output


# ---- Wiki ----


def test_wiki_list(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    articles = [
        {
            "id": "a1",
            "slug": "test-article",
            "title": "Test Article",
            "page_type": "source",
            "source_count": 2,
        },
        {
            "id": "a2",
            "slug": "another-article",
            "title": "Another Article",
            "page_type": "concept",
            "source_count": 1,
        },
    ]
    resp = _mock_response(json_data=articles)

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["wiki", "list"])

    assert result.exit_code == 0
    assert "test-article" in result.output
    assert "another-article" in result.output
    assert "2 article(s)" in result.output


def test_wiki_list_empty(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(json_data=[])

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["wiki", "list"])

    assert result.exit_code == 0
    assert "No articles found" in result.output


def test_wiki_show(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    article = {
        "id": "a1",
        "slug": "test-article",
        "title": "Test Article",
        "content": "# Test Content\n\nThis is a test.",
        "page_type": "source",
        "concepts": ["testing", "demo"],
    }
    resp = _mock_response(json_data=article)

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["wiki", "show", "test-article"])

    assert result.exit_code == 0
    assert "# Test Article" in result.output
    assert "# Test Content" in result.output
    assert "testing, demo" in result.output


# ---- Ingest ----


def test_ingest_url(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(json_data={"id": "s1", "title": "Example Page", "source_type": "url", "status": "ingested"})

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.post = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["ingest", "url", "https://example.com"])

    assert result.exit_code == 0
    assert "Source ingested: Example Page" in result.output


def test_ingest_text(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(json_data={"id": "s2", "title": "My Note", "status": "ingested"})

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.post = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["ingest", "text", "Some important note"])

    assert result.exit_code == 0
    assert "Source ingested: My Note" in result.output


# ---- Query ----


def test_ask(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(
        json_data={
            "query": {
                "id": "q1",
                "answer": "The answer is 42.",
                "confidence": "high",
                "question": "What is the answer?",
            },
            "conversation": {"id": "conv-1", "title": "Test"},
        }
    )

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.post = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["ask", "What is the answer?"])

    assert result.exit_code == 0
    assert "The answer is 42." in result.output
    assert "high" in result.output
    assert "conv-1" in result.output


# ---- Status ----


def test_status(runner, tmp_token):
    tmp_token.write_text("test-token\n")
    resp = _mock_response(
        json_data={
            "article_count": 15,
            "source_count": 23,
            "concept_count": 8,
        }
    )

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(return_value=resp)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "WikiMind Status" in result.output
    assert "Article Count: 15" in result.output
    assert "Source Count: 23" in result.output


# ---- Error handling ----


def test_server_not_running(runner, tmp_token):
    tmp_token.write_text("test-token\n")

    with patch("wikimind.cli.client.httpx.Client") as mock_cls:
        client_instance = MagicMock()
        client_instance.get = MagicMock(side_effect=_raise_connect_error)
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        mock_cls.return_value = client_instance

        result = runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "Cannot connect" in result.output


def _raise_connect_error(*args, **kwargs):
    raise __import__("httpx").ConnectError("Connection refused")


# ---- Client helpers ----


def test_save_and_load_token(tmp_token):
    assert load_token() is None
    save_token("my-jwt-token")
    assert load_token() == "my-jwt-token"
    clear_token()
    assert load_token() is None
