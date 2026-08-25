# memo-mcp

`memo-mcp` is a guarded Streamable HTTP MCP gateway for a private, self-hosted
Mem0 REST API. It exposes a small, non-destructive memory-tool surface while
keeping Mem0, PostgreSQL and internal API credentials off the public network.

It is designed as a reference implementation for **one trusted memory scope**.
Before allowing multiple people to use it, integrate a server-side policy
adapter that derives the memory scope from authenticated membership. Never let
a browser or MCP client choose `MEMORY_SCOPE`.

## Security model

- Mem0 remains private; expose only this gateway through a reverse proxy.
- Non-browser clients use a distinct, revocable bearer token.
- Browser clients can use OAuth/OIDC token introspection with exact issuer,
  audience, immutable subject and scope checks.
- `memo_remember_fact` requires `mem0.write` for OAuth clients.
- The gateway deliberately provides no memory-deletion tool. Perform deletion
  through a separate, private administrative workflow with explicit approval.
- The gateway rejects common credential and private-key formats before they can
  be written to memory. This is a safety net, not a replacement for operator
  policy.
- A caller must never select its own memory scope. In multi-user deployments,
  a trusted application must derive that scope from server-side membership.

## Quick start

1. Copy `.env.example` to `.env` and replace every placeholder with your own
   private values. Do not commit `.env`.
2. Create a private Docker network and start the service with
   `docker compose -f compose.example.yml up -d --build`.
3. Route only the gateway through HTTPS. Do not publish Mem0, PostgreSQL or
   any populated environment file.
4. Verify that the protected-resource metadata returns `200` when OAuth is
   enabled and that an anonymous `/mcp` request returns `401`.

## Tools

- `memo_search_memory`
- `memo_remember_fact`

## Configuration

See `.env.example`. `PUBLIC_MCP_URL`, `MCP_ALLOWED_HOSTS`, and
`MCP_ALLOWED_ORIGINS` must describe your own HTTPS endpoint. The gateway calls
the underlying Mem0 API using `X-API-Key`.

`MCP_ALLOWED_HOSTS` is mandatory. The container build context excludes `.env`,
Git metadata, and local Python artifacts so they cannot be copied to an image
by accident.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

This project uses the official [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
