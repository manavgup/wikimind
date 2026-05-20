# ADR-027: MCP Authentication — OAuth 2.1 + Personal Access Tokens

**Status:** Accepted  
**Date:** 2026-05-17 (updated 2026-05-18)  
**Context:** WikiMind's MCP server needs authentication for Streamable HTTP transport. The web UI uses Google/GitHub OAuth, but MCP clients have different auth needs depending on their capabilities.

## Decision

Support **three auth methods**, in priority order:

1. **OAuth 2.1** (MCP Authorization spec) — for Claude.ai Custom Connectors and compliant MCP clients
2. **Personal Access Tokens (PATs)** — for Claude Desktop, MCP Inspector, CLI tools, and non-OAuth clients
3. **JWT tokens** — for programmatic/internal use

## Auth Architecture

There are **two separate auth concerns** in MCP:

### 1. MCP Client → WikiMind (who is this user?)

This is covered by the **MCP Authorization spec** (OAuth 2.1). Claude.ai Custom Connectors handle this natively:

```
User opens Claude.ai → Settings → Connectors → Add Custom Connector
  → enters: https://wikimind.fly.dev/mcp
  → Claude.ai redirects to WikiMind's OAuth
  → User logs in with Google/GitHub (existing OAuth flow)
  → WikiMind issues OAuth access token
  → Claude.ai stores token, uses it for all MCP requests
  → Done — zero token copying needed
```

For clients that don't support OAuth (Claude Desktop, MCP Inspector, CLI agents):

```
User logs into WikiMind web UI → Settings → API Tokens → Generate
  → copies wmk_abc123... into client config
  → client sends Authorization: Bearer wmk_abc123...
  → WikiMind validates via hash lookup
```

### 2. WikiMind → Third-party services (WikiMind needs access to external APIs)

This uses **URL mode elicitation** (MCP spec 2025-11-25). Example: WikiMind needs to ingest from a user's private Google Drive.

```
User asks Claude: "Save my Google Doc to the wiki"
  → Claude calls wiki_ingest_url(google_drive_url)
  → WikiMind detects Google auth needed
  → WikiMind sends URL elicitation: "Please authorize Google Drive access"
  → Client opens browser to WikiMind's Google OAuth page
  → User authorizes → WikiMind stores Google tokens
  → WikiMind fetches the doc and ingests it
```

This is a future enhancement (requires FastMCP URL elicitation support).

## OAuth 2.1 Implementation (MCP Authorization)

WikiMind already has Google/GitHub OAuth via the web UI. To support MCP Authorization, WikiMind needs to act as an **OAuth 2.1 Authorization Server**:

### Endpoints to add:

```
GET  /mcp/.well-known/oauth-authorization-server  → Server metadata
GET  /mcp/authorize                                → Authorization endpoint
POST /mcp/token                                    → Token endpoint
POST /mcp/revoke                                   → Token revocation
GET  /mcp/register                                 → Dynamic client registration (optional)
```

### Flow:

1. MCP client discovers OAuth metadata at `/.well-known/oauth-authorization-server`
2. Client redirects user to `/mcp/authorize` with PKCE challenge
3. WikiMind shows login page (Google/GitHub buttons — existing UI)
4. User authenticates → WikiMind issues authorization code
5. Client exchanges code for access token at `/mcp/token`
6. Client uses access token for all MCP requests

WikiMind can reuse its existing OAuth infrastructure — the user authenticates with Google/GitHub as usual, and WikiMind wraps the session in an OAuth 2.1 access token for the MCP client.

## Personal Access Tokens (PATs)

For clients that don't support OAuth (Claude Desktop config files, MCP Inspector, CI agents):

### Token Design

- **Format:** `wmk_<32 hex chars>` — prefix makes tokens identifiable in logs/config
- **Storage:** SHA-256 hash only. Plaintext never stored after generation.
- **Prefix stored:** First 8 chars (`wmk_ab12...`) for identification in the management UI
- **Expiry:** Optional. `None` = never expires.
- **Revocation:** Soft-delete via `revoked` flag. Immediate effect on next request.

### Management API

```
POST   /api/settings/mcp-tokens       → Generate new token (returns plaintext ONCE)
GET    /api/settings/mcp-tokens       → List tokens (name, prefix, created, last_used)
DELETE /api/settings/mcp-tokens/{id}  → Revoke a token
```

### Client Configuration

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "wikimind": {
      "url": "https://wikimind.fly.dev/mcp",
      "headers": {"Authorization": "Bearer wmk_abc123..."}
    }
  }
}
```

## Auth Provider (implementation)

The MCP auth provider tries methods in order:

```python
class WikiMindAuthProvider(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken:
        if token.startswith("wmk_"):
            return await self._verify_pat(token)     # PAT lookup
        return await self._verify_jwt(token)          # JWT or OAuth access token
```

Future: add `_verify_oauth_token()` when OAuth 2.1 AS is implemented.

## Implementation Priority

| Phase | Auth Method | For | Status |
|-------|-----------|-----|--------|
| **Phase 1** | PAT tokens | Claude Desktop, Inspector, CLI agents | Built (PR #756) |
| **Phase 2** | OAuth 2.1 AS | Claude.ai Custom Connectors | Planned |
| **Phase 3** | URL elicitation | Third-party service auth (Google Drive, etc.) | Future |

## Alternatives Considered

1. **PAT-only** — works but requires manual token copying. OAuth is better UX for Claude.ai.
2. **OAuth-only** — excludes CLI tools and Claude Desktop (which uses config files, not browser auth).
3. **Magic link auth** — too slow for MCP client connection.
4. **URL elicitation for MCP auth** — the MCP spec explicitly says "MUST NOT use URL elicitation for MCP client auth" — that's what MCP Authorization is for.

## Consequences

- Phase 1 (PATs): works today for all clients
- Phase 2 (OAuth): enables zero-config connection from Claude.ai
- Phase 3 (URL elicitation): enables rich third-party integrations
- Each phase is additive — no breaking changes
