"""MCP Client Manager — connects to external MCP servers and discovers/calls tools.

Manages persistent connections to configured external MCP servers so the Q&A
agent can invoke external tools during query processing. Each server is connected
via either stdio (subprocess) or HTTP transport. Connection failures are logged
and the server is skipped — they never crash the application.

Configuration is via WIKIMIND_MCP__EXTERNAL_SERVERS as a JSON-encoded list of
server configs, each with name, transport, and transport-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from wikimind.config import get_settings

if TYPE_CHECKING:
    from mcp.types import Tool

log = structlog.get_logger()


@dataclass
class ExternalToolInfo:
    """Metadata about a discovered tool from an external MCP server."""

    server_name: str
    tool: Tool


@dataclass
class MCPClientManager:
    """Manage connections to external MCP servers and provide tool discovery/calling.

    Lifecycle:
        - Call ``start()`` during app startup to connect to all configured servers
          and discover their tools.
        - Call ``stop()`` during app shutdown to close all connections.
        - Use ``list_tools()`` to get all discovered tools across all servers.
        - Use ``call_tool()`` to invoke a tool on a specific server.

    Connection failures during ``start()`` are logged and the server is skipped.
    The rest of the application continues without that server's tools.
    """

    _clients: dict[str, Client] = field(default_factory=dict)
    _tools: dict[str, list[Tool]] = field(default_factory=dict)
    _started: bool = False

    async def start(self) -> None:
        """Connect to all configured external MCP servers and discover tools.

        Reads server configs from settings. For each server, creates a Client
        with the appropriate transport, connects, and discovers available tools.
        Failures are logged and the server is skipped.
        """
        if self._started:
            return

        settings = get_settings()
        servers = settings.mcp.external_servers

        if not servers:
            log.info("No external MCP servers configured")
            self._started = True
            return

        for server_cfg in servers:
            name = server_cfg.name
            try:
                client = self._create_client(server_cfg)
                await client.__aenter__()
                tools = await client.list_tools()
                self._clients[name] = client
                self._tools[name] = tools
                log.info(
                    "Connected to external MCP server",
                    server=name,
                    tool_count=len(tools),
                    tools=[t.name for t in tools],
                )
            except Exception:
                log.warning(
                    "Failed to connect to external MCP server — skipping",
                    server=name,
                    exc_info=True,
                )

        self._started = True
        total = sum(len(t) for t in self._tools.values())
        log.info("MCP client manager started", servers=len(self._clients), total_tools=total)

    async def stop(self) -> None:
        """Disconnect from all external MCP servers."""
        if not self._started:
            return

        for name, client in self._clients.items():
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                log.warning("Error closing MCP client", server=name, exc_info=True)

        self._clients.clear()
        self._tools.clear()
        self._started = False
        log.info("MCP client manager stopped")

    def list_tools(self) -> list[ExternalToolInfo]:
        """Return all discovered tools across all connected servers.

        Returns:
            List of :class:`ExternalToolInfo` with server name and tool metadata.
        """
        result: list[ExternalToolInfo] = []
        for server_name, tools in self._tools.items():
            result.extend(ExternalToolInfo(server_name=server_name, tool=tool) for tool in tools)
        return result

    def get_tools_for_server(self, server_name: str) -> list[Tool]:
        """Return tools discovered from a specific server.

        Args:
            server_name: The configured name of the MCP server.

        Returns:
            List of MCP Tool objects, or empty list if server not connected.
        """
        return self._tools.get(server_name, [])

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Call a tool on a specific external MCP server.

        Args:
            server_name: The configured name of the MCP server.
            tool_name: The name of the tool to call.
            arguments: Optional arguments to pass to the tool.

        Returns:
            The text content of the tool result.

        Raises:
            ValueError: If the server is not connected.
            RuntimeError: If the tool call fails.
        """
        client = self._clients.get(server_name)
        if client is None:
            msg = f"MCP server not connected: {server_name}"
            raise ValueError(msg)

        try:
            result = await client.call_tool(tool_name, arguments)
            # Extract text content from the result
            parts = [content_item.text for content_item in result.content if hasattr(content_item, "text")]
            return "\n".join(parts) if parts else ""
        except Exception as exc:
            log.error(
                "MCP tool call failed",
                server=server_name,
                tool=tool_name,
                error=str(exc),
            )
            msg = f"Tool call failed: {server_name}/{tool_name}: {exc}"
            raise RuntimeError(msg) from exc

    @staticmethod
    def _create_client(server_cfg: Any) -> Client:
        """Create a fastmcp Client with the appropriate transport for a server config.

        Args:
            server_cfg: An :class:`MCPServerEntry` from settings.

        Returns:
            A configured :class:`Client` instance (not yet connected).
        """
        transport: StdioTransport | StreamableHttpTransport
        if server_cfg.transport == "stdio":
            transport = StdioTransport(
                command=server_cfg.command,
                args=server_cfg.args,
                env=server_cfg.env,
            )
        elif server_cfg.transport == "http":
            transport = StreamableHttpTransport(
                url=server_cfg.url,
                headers=server_cfg.headers,
            )
        else:
            msg = f"Unsupported MCP transport: {server_cfg.transport}"
            raise ValueError(msg)

        return Client(transport=transport, timeout=server_cfg.timeout)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_manager: MCPClientManager | None = None


def get_mcp_client_manager() -> MCPClientManager:
    """Return the singleton MCPClientManager instance.

    Creates the instance on first call. The caller is responsible for
    calling ``start()`` and ``stop()`` during app lifecycle.
    """
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
    return _manager


def reset_mcp_client_manager() -> None:
    """Reset the singleton for testing purposes."""
    global _manager
    _manager = None
