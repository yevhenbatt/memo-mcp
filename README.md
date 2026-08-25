# memo-mcp

`memo-mcp` is a guarded Streamable HTTP MCP gateway for a private, self-hosted
Mem0 REST API. It exposes only a small memory-tool surface while keeping Mem0,
PostgreSQL and internal API credentials off the public network.

It is designed as a reference implementation. You must connect it to your own
identity and workspace policy before allowing multiple people to use it.

## Security model

- Mem0 remains private; expose only this gateway through a reverse proxy.
- Non-browser clients use a distinct, revocable bearer token.
- Browser clients can use OAuth/OIDC token introspection with exact issuer,
  audience, immutable subject and scope checks.
- `memo_remember_fact` requires `mem0.write` for OAuth clients.
- OAuth clients cannot delete memories. Deletion requires an explicitly
  authorised non-browser path.
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
- `memo_forget_memory` — irreversible; OAuth clients are always denied.

## Configuration

See `.env.example`. `PUBLIC_MCP_URL`, `MCP_ALLOWED_HOSTS`, and
`MCP_ALLOWED_ORIGINS` must describe your own HTTPS endpoint. The gateway calls
the underlying Mem0 API using `X-API-Key`.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

This project uses the official [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
