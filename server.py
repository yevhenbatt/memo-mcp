"""Guarded Streamable HTTP MCP gateway for a private Mem0 REST API."""

from __future__ import annotations

import contextvars
import hmac
import json
import logging
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("memo_mcp.oauth")

CHARACTER_LIMIT = 12_000
MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://mem0-api:8000").rstrip("/")
MEM0_API_KEY = os.environ.get("MEM0_API_KEY", "")
MCP_BEARER_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")
MEMORY_SCOPE = os.environ.get("MEMORY_SCOPE", "")
PUBLIC_MCP_URL = os.environ.get("PUBLIC_MCP_URL", "").rstrip("/")
RESOURCE_NAME = os.environ.get("MEMORY_RESOURCE_NAME", "Self-hosted shared memory")
OAUTH_ISSUER_URL = os.environ.get("OAUTH_ISSUER_URL", "").rstrip("/")
OAUTH_INTROSPECTION_URL = os.environ.get("OAUTH_INTROSPECTION_URL", "")
OAUTH_RESOURCE_CLIENT_ID = os.environ.get("OAUTH_RESOURCE_CLIENT_ID", "")
OAUTH_RESOURCE_CLIENT_SECRET = os.environ.get("OAUTH_RESOURCE_CLIENT_SECRET", "")
OAUTH_ALLOWED_SUB = os.environ.get("OAUTH_ALLOWED_SUB", "")
OAUTH_REQUIRED_SCOPE = os.environ.get("OAUTH_REQUIRED_SCOPE", "mem0.read")
OAUTH_WRITE_SCOPE = os.environ.get("OAUTH_WRITE_SCOPE", "mem0.write")


def _csv_setting(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


OAUTH_CONFIGURATION = (
    OAUTH_ISSUER_URL,
    OAUTH_INTROSPECTION_URL,
    OAUTH_RESOURCE_CLIENT_ID,
    OAUTH_RESOURCE_CLIENT_SECRET,
    OAUTH_ALLOWED_SUB,
)
OAUTH_ENABLED = any(OAUTH_CONFIGURATION)
if not MEM0_API_KEY or not MCP_BEARER_TOKEN or not MEMORY_SCOPE:
    raise RuntimeError("MEM0_API_KEY, MCP_BEARER_TOKEN, and MEMORY_SCOPE must be configured.")
if OAUTH_ENABLED and (not all(OAUTH_CONFIGURATION) or not PUBLIC_MCP_URL):
    raise RuntimeError("OAuth requires all OAUTH_* settings and PUBLIC_MCP_URL.")

oauth_subject: contextvars.ContextVar[str | None] = contextvars.ContextVar("oauth_subject", default=None)
oauth_write_allowed: contextvars.ContextVar[bool] = contextvars.ContextVar("oauth_write_allowed", default=False)

mcp = FastMCP(
    "memo_mcp",
    host="0.0.0.0",
    port=8080,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_csv_setting("MCP_ALLOWED_HOSTS"),
        allowed_origins=_csv_setting("MCP_ALLOWED_ORIGINS"),
    ),
    instructions=(
        "Search before recording a duplicate. Store durable facts and decisions only; "
        "never store credentials, tokens, private keys, or transient chat content."
    ),
)


class GatewayAuthenticationMiddleware:
    """Accept a dedicated bearer token or a validated OAuth access token."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") == "/.well-known/oauth-protected-resource":
            await self._protected_resource_metadata(send)
            return
        authorization = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
        token = authorization.removeprefix("Bearer ")
        if authorization.startswith("Bearer ") and hmac.compare_digest(token, MCP_BEARER_TOKEN):
            await self.app(scope, receive, send)
            return
        access = await self._oauth_access(token) if authorization.startswith("Bearer ") else None
        if access:
            subject, can_write = access
            subject_token = oauth_subject.set(subject)
            write_token = oauth_write_allowed.set(can_write)
            try:
                await self.app(scope, receive, send)
            finally:
                oauth_write_allowed.reset(write_token)
                oauth_subject.reset(subject_token)
            return
        await self._unauthorized(send)

    async def _oauth_access(self, token: str) -> tuple[str, bool] | None:
        if not OAUTH_ENABLED or not token:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    OAUTH_INTROSPECTION_URL,
                    data={"token": token},
                    auth=(OAUTH_RESOURCE_CLIENT_ID, OAUTH_RESOURCE_CLIENT_SECRET),
                )
            response.raise_for_status()
            claims = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("OAuth introspection failed: %s", type(error).__name__)
            return None
        scopes = set(str(claims.get("scope", "")).split())
        audience = claims.get("aud", [])
        if isinstance(audience, str):
            audience = [audience]
        failures = []
        if not claims.get("active"):
            failures.append("inactive")
        if claims.get("sub") != OAUTH_ALLOWED_SUB:
            failures.append("subject")
        if OAUTH_REQUIRED_SCOPE not in scopes:
            failures.append("scope")
        if claims.get("iss") and claims["iss"].rstrip("/") != OAUTH_ISSUER_URL:
            failures.append("issuer")
        if PUBLIC_MCP_URL not in audience:
            failures.append("audience")
        if failures:
            logger.warning("OAuth token rejected: %s", ",".join(failures))
            return None
        return OAUTH_ALLOWED_SUB, OAUTH_WRITE_SCOPE in scopes

    async def _protected_resource_metadata(self, send: Send) -> None:
        if not OAUTH_ENABLED:
            await self._not_found(send)
            return
        await self._json_response(send, 200, {
            "resource": PUBLIC_MCP_URL,
            "resource_name": RESOURCE_NAME,
            "authorization_servers": [OAUTH_ISSUER_URL],
            "scopes_supported": [OAUTH_REQUIRED_SCOPE, OAUTH_WRITE_SCOPE, "offline_access"],
            "bearer_methods_supported": ["header"],
        })

    async def _unauthorized(self, send: Send) -> None:
        body = b'{"error":"Unauthorized MCP request."}'
        metadata = f"{PUBLIC_MCP_URL}/.well-known/oauth-protected-resource".replace("/mcp/.", "/.")
        challenge = f'Bearer realm="memo_mcp", resource_metadata="{metadata}"' if OAUTH_ENABLED else "Bearer"
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"), (b"www-authenticate", challenge.encode()),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})

    async def _not_found(self, send: Send) -> None:
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def _json_response(self, send: Send, status: int, value: Any) -> None:
        body = json.dumps(value).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})


def _truncate(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= CHARACTER_LIMIT else text[:CHARACTER_LIMIT] + "\n\n[Response truncated.]"


async def _mem0_request(method: str, path: str, **kwargs: Any) -> Any:
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(method, f"{MEM0_API_URL}{path}", headers={"X-API-Key": MEM0_API_KEY}, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {"ok": True}
    except httpx.HTTPStatusError as error:
        return {"error": f"Mem0 request failed with HTTP {error.response.status_code}."}
    except httpx.TimeoutException:
        return {"error": "Mem0 request timed out. Retry once."}
    except httpx.HTTPError:
        return {"error": "The private Mem0 service is unavailable."}


@mcp.tool(name="memo_search_memory", annotations={"readOnlyHint": True, "destructiveHint": False})
async def memo_search_memory(query: str, limit: int = 5) -> str:
    """Find relevant durable facts in the approved memory scope."""
    query = query.strip()
    if not 1 <= len(query) <= 1_000 or not 1 <= limit <= 10:
        return _truncate({"error": "query must be 1–1,000 characters and limit must be 1–10."})
    return _truncate(await _mem0_request("POST", "/search", json={"query": query, "filters": {"user_id": MEMORY_SCOPE}, "top_k": limit}))


@mcp.tool(name="memo_remember_fact", annotations={"readOnlyHint": False, "destructiveHint": False})
async def memo_remember_fact(fact: str) -> str:
    """Store one explicit, durable and non-secret fact."""
    if oauth_subject.get() is not None and not oauth_write_allowed.get():
        return _truncate({"error": "OAuth client needs the configured write scope to save a fact."})
    fact = fact.strip()
    if not 1 <= len(fact) <= 2_000:
        return _truncate({"error": "fact must be 1–2,000 characters."})
    return _truncate(await _mem0_request("POST", "/memories", json={
        "messages": [{"role": "user", "content": fact}], "user_id": MEMORY_SCOPE, "infer": False,
    }))


@mcp.tool(name="memo_forget_memory", annotations={"readOnlyHint": False, "destructiveHint": True})
async def memo_forget_memory(memory_id: str) -> str:
    """Permanently delete one memory after explicit out-of-band approval."""
    if oauth_subject.get() is not None:
        return _truncate({"error": "Memory deletion is disabled for OAuth clients."})
    memory_id = memory_id.strip()
    if len(memory_id) != 36:
        return _truncate({"error": "memory_id must be a UUID returned by a memory tool."})
    return _truncate(await _mem0_request("DELETE", f"/memories/{memory_id}"))


app = GatewayAuthenticationMiddleware(mcp.streamable_http_app())
