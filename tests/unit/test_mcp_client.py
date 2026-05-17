"""Tests for the MCP Client Manager.

Tests cover:
  - Configuration parsing and client creation
  - Connection lifecycle (start/stop)
  - Tool discovery from external servers
  - Tool calling with mocked transports
  - Graceful handling of connection failures
  - Singleton accessor behavior
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import Tool

from wikimind.config import MCPConfig, MCPServerEntry
from wikimind.mcp.client import (
    ExternalToolInfo,
    MCPClientManager,
    get_mcp_client_manager,
    reset_mcp_client_manager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton between tests."""
    reset_mcp_client_manager()
    yield
    reset_mcp_client_manager()


@pytest.fixture
def stdio_server_entry() -> MCPServerEntry:
    """A sample stdio MCP server config."""
    return MCPServerEntry(
        name="test-stdio",
        transport="stdio",
        command="python",
        args=["-m", "test_server"],
        timeout=10.0,
    )


@pytest.fixture
def http_server_entry() -> MCPServerEntry:
    """A sample HTTP MCP server config."""
    return MCPServerEntry(
        name="test-http",
        transport="http",
        url="http://localhost:9100",
        timeout=15.0,
    )


@pytest.fixture
def sample_tools() -> list[Tool]:
    """Sample MCP tools for mocking."""
    return [
        Tool(
            name="get_weather",
            description="Get current weather for a location",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="search_web",
            description="Search the web for information",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# MCPServerEntry validation
# ---------------------------------------------------------------------------


class TestMCPServerEntry:
    """Test MCPServerEntry configuration model."""

    def test_stdio_entry_defaults(self):
        entry = MCPServerEntry(name="test", transport="stdio", command="echo")
        assert entry.name == "test"
        assert entry.transport == "stdio"
        assert entry.command == "echo"
        assert entry.args == []
        assert entry.env is None
        assert entry.timeout == 30.0

    def test_http_entry(self):
        entry = MCPServerEntry(
            name="remote",
            transport="http",
            url="http://example.com:9000",
            headers={"Authorization": "Bearer abc"},
            timeout=60.0,
        )
        assert entry.url == "http://example.com:9000"
        assert entry.headers == {"Authorization": "Bearer abc"}
        assert entry.timeout == 60.0


class TestMCPConfig:
    """Test MCPConfig defaults and parsing."""

    def test_defaults(self):
        cfg = MCPConfig()
        assert cfg.external_servers == []
        assert cfg.client_enabled is False

    def test_with_servers(self):
        cfg = MCPConfig(
            client_enabled=True,
            external_servers=[
                MCPServerEntry(name="s1", transport="stdio", command="cmd"),
            ],
        )
        assert cfg.client_enabled is True
        assert len(cfg.external_servers) == 1


# ---------------------------------------------------------------------------
# MCPClientManager — lifecycle
# ---------------------------------------------------------------------------


class TestMCPClientManagerLifecycle:
    """Test start/stop lifecycle of the manager."""

    @pytest.mark.asyncio
    async def test_start_with_no_servers(self):
        """Start succeeds with no configured servers."""
        manager = MCPClientManager()
        with patch("wikimind.mcp.client.get_settings") as mock_settings:
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[])
            await manager.start()

        assert manager._started is True
        assert manager.list_tools() == []

    @pytest.mark.asyncio
    async def test_start_connects_to_servers(self, stdio_server_entry, sample_tools):
        """Start connects to configured servers and discovers tools."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        assert manager._started is True
        assert len(manager.list_tools()) == 2
        assert manager._clients["test-stdio"] is mock_client

    @pytest.mark.asyncio
    async def test_start_skips_failed_server(self, stdio_server_entry, http_server_entry, sample_tools):
        """If one server fails to connect, others still work."""
        manager = MCPClientManager()

        good_client = AsyncMock()
        good_client.__aenter__ = AsyncMock(return_value=good_client)
        good_client.__aexit__ = AsyncMock(return_value=None)
        good_client.list_tools = AsyncMock(return_value=sample_tools)

        bad_client = AsyncMock()
        bad_client.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))

        def create_client_side_effect(cfg):
            if cfg.name == "test-stdio":
                return bad_client
            return good_client

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", side_effect=create_client_side_effect),
        ):
            mock_settings.return_value.mcp = MCPConfig(
                client_enabled=True,
                external_servers=[stdio_server_entry, http_server_entry],
            )
            await manager.start()

        assert manager._started is True
        # Only the HTTP server should be connected
        assert "test-http" in manager._clients
        assert "test-stdio" not in manager._clients
        assert len(manager.list_tools()) == 2

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Calling start() twice does not re-connect."""
        manager = MCPClientManager()
        with patch("wikimind.mcp.client.get_settings") as mock_settings:
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[])
            await manager.start()
            await manager.start()  # Should not raise

        assert manager._started is True

    @pytest.mark.asyncio
    async def test_stop_disconnects_clients(self, stdio_server_entry, sample_tools):
        """Stop closes all client connections."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()
            await manager.stop()

        assert manager._started is False
        assert manager._clients == {}
        assert manager._tools == {}
        mock_client.__aexit__.assert_called_once_with(None, None, None)

    @pytest.mark.asyncio
    async def test_stop_handles_client_close_error(self, stdio_server_entry, sample_tools):
        """Stop logs but doesn't raise if a client close fails."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(side_effect=RuntimeError("close failed"))
        mock_client.list_tools = AsyncMock(return_value=sample_tools)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()
            # Should not raise
            await manager.stop()

        assert manager._started is False


# ---------------------------------------------------------------------------
# MCPClientManager — tool discovery
# ---------------------------------------------------------------------------


class TestMCPClientManagerTools:
    """Test tool discovery and listing."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_external_tool_info(self, stdio_server_entry, sample_tools):
        """list_tools returns ExternalToolInfo objects with server names."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        tools = manager.list_tools()
        assert len(tools) == 2
        assert all(isinstance(t, ExternalToolInfo) for t in tools)
        assert all(t.server_name == "test-stdio" for t in tools)
        assert tools[0].tool.name == "get_weather"
        assert tools[1].tool.name == "search_web"

    @pytest.mark.asyncio
    async def test_get_tools_for_server(self, stdio_server_entry, sample_tools):
        """get_tools_for_server returns tools for a specific server."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        assert len(manager.get_tools_for_server("test-stdio")) == 2
        assert manager.get_tools_for_server("nonexistent") == []


# ---------------------------------------------------------------------------
# MCPClientManager — tool calling
# ---------------------------------------------------------------------------


class TestMCPClientManagerCallTool:
    """Test tool calling functionality."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self, stdio_server_entry, sample_tools):
        """call_tool returns text content from the tool result."""
        manager = MCPClientManager()

        from mcp.types import TextContent

        @dataclass
        class CallToolResult:
            content: list[Any]

        mock_result = CallToolResult(content=[TextContent(type="text", text="Sunny, 72F")])

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)
        mock_client.call_tool = AsyncMock(return_value=mock_result)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        result = await manager.call_tool("test-stdio", "get_weather", {"city": "NYC"})
        assert result == "Sunny, 72F"
        mock_client.call_tool.assert_called_once_with("get_weather", {"city": "NYC"})

    @pytest.mark.asyncio
    async def test_call_tool_server_not_connected(self):
        """call_tool raises ValueError for unknown servers."""
        manager = MCPClientManager()
        manager._started = True

        with pytest.raises(ValueError, match="MCP server not connected: unknown"):
            await manager.call_tool("unknown", "some_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_failure_raises_runtime_error(self, stdio_server_entry, sample_tools):
        """call_tool wraps exceptions in RuntimeError."""
        manager = MCPClientManager()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)
        mock_client.call_tool = AsyncMock(side_effect=TimeoutError("timed out"))

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        with pytest.raises(RuntimeError, match="Tool call failed"):
            await manager.call_tool("test-stdio", "get_weather", {"city": "NYC"})

    @pytest.mark.asyncio
    async def test_call_tool_multi_content(self, stdio_server_entry, sample_tools):
        """call_tool concatenates multiple text content items."""
        manager = MCPClientManager()

        from mcp.types import TextContent

        @dataclass
        class CallToolResult:
            content: list[Any]

        mock_result = CallToolResult(content=[TextContent(type="text", text="Line 1"), TextContent(type="text", text="Line 2")])

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=sample_tools)
        mock_client.call_tool = AsyncMock(return_value=mock_result)

        with (
            patch("wikimind.mcp.client.get_settings") as mock_settings,
            patch.object(MCPClientManager, "_create_client", return_value=mock_client),
        ):
            mock_settings.return_value.mcp = MCPConfig(client_enabled=True, external_servers=[stdio_server_entry])
            await manager.start()

        result = await manager.call_tool("test-stdio", "search_web", {"query": "test"})
        assert result == "Line 1\nLine 2"


# ---------------------------------------------------------------------------
# MCPClientManager — client creation
# ---------------------------------------------------------------------------


class TestMCPClientManagerCreateClient:
    """Test _create_client transport selection."""

    def test_create_stdio_client(self, stdio_server_entry):
        """Creates Client with StdioTransport for stdio servers."""
        with (
            patch("wikimind.mcp.client.StdioTransport") as mock_transport,
            patch("wikimind.mcp.client.Client") as mock_client_cls,
        ):
            MCPClientManager._create_client(stdio_server_entry)
            mock_transport.assert_called_once_with(
                command="python",
                args=["-m", "test_server"],
                env=None,
            )
            mock_client_cls.assert_called_once()

    def test_create_http_client(self, http_server_entry):
        """Creates Client with StreamableHttpTransport for HTTP servers."""
        with (
            patch("wikimind.mcp.client.StreamableHttpTransport") as mock_transport,
            patch("wikimind.mcp.client.Client") as mock_client_cls,
        ):
            MCPClientManager._create_client(http_server_entry)
            mock_transport.assert_called_once_with(
                url="http://localhost:9100",
                headers=None,
            )
            mock_client_cls.assert_called_once()

    def test_create_client_unsupported_transport(self):
        """Raises ValueError for unsupported transport type."""
        entry = MagicMock()
        entry.transport = "grpc"
        with pytest.raises(ValueError, match="Unsupported MCP transport: grpc"):
            MCPClientManager._create_client(entry)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


class TestSingleton:
    """Test the module-level singleton accessor."""

    def test_get_returns_same_instance(self):
        """get_mcp_client_manager returns the same instance."""
        m1 = get_mcp_client_manager()
        m2 = get_mcp_client_manager()
        assert m1 is m2

    def test_reset_clears_singleton(self):
        """reset_mcp_client_manager creates a fresh instance next time."""
        m1 = get_mcp_client_manager()
        reset_mcp_client_manager()
        m2 = get_mcp_client_manager()
        assert m1 is not m2


# ---------------------------------------------------------------------------
# QA Agent integration — _format_external_tools_block
# ---------------------------------------------------------------------------


class TestFormatExternalToolsBlock:
    """Test the external tools prompt formatting."""

    def test_empty_tools(self):
        from wikimind.engine.qa_agent import _format_external_tools_block

        assert _format_external_tools_block([]) == ""

    def test_formats_tools_with_params(self, sample_tools):
        from wikimind.engine.qa_agent import _format_external_tools_block

        infos = [
            ExternalToolInfo(server_name="weather-srv", tool=sample_tools[0]),
            ExternalToolInfo(server_name="search-srv", tool=sample_tools[1]),
        ]
        result = _format_external_tools_block(infos)
        assert "weather-srv/get_weather" in result
        assert "search-srv/search_web" in result
        assert "(params: city)" in result
        assert "(params: query, limit)" in result
        assert "tool_calls" in result

    def test_formats_tool_without_params(self):
        from wikimind.engine.qa_agent import _format_external_tools_block

        tool = Tool(
            name="ping",
            description="Ping the server",
            inputSchema={"type": "object", "properties": {}},
        )
        infos = [ExternalToolInfo(server_name="infra", tool=tool)]
        result = _format_external_tools_block(infos)
        assert "infra/ping" in result
        assert "Ping the server" in result
