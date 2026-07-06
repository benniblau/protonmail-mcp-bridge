# CLAUDE.md

Guidance for working in this repo. Keep it current when architecture or deploy steps change.

## What this is

A Docker Compose stack with two services (`docker-compose.yml`):

- **`protonmail-bridge`** — the official Proton Mail Bridge (v3.25.0) built from source, headless, using a `gpg`/`pass` keychain. It speaks IMAP (`1143`) and SMTP (`1025`) with STARTTLS + a self-signed cert, reachable only on the private `mailnet` Docker network (not published to the host by default).
- **`mcp-server`** — a Python **FastMCP** streamable-HTTP server (`mcp-server/server.py` + `mcp-server/mail.py`) that exposes full read/write mail tools over MCP, gated by a single static bearer token.

Data flow: MCP client → `mcp-server` (HTTP + bearer) → Proton Bridge (IMAP/SMTP over `mailnet`) → Proton.

## Layout

- `mcp-server/server.py` — FastMCP app: tool definitions (thin wrappers), auth, and the `run()` entrypoint.
- `mcp-server/mail.py` — all IMAP/SMTP logic against the bridge (`imap_tools` + `smtplib`).
- `protonmail-bridge/` — Dockerfile + entrypoint that build/bootstrap the bridge.
- `.env` — all secrets and runtime config (gitignored). `.env.example` documents every key.

## Config (.env)

Never commit `.env` or paste its secrets into tracked files (including this one). Keys that matter:

- `BRIDGE_USERNAME` / `BRIDGE_PASSWORD` — bridge-generated IMAP/SMTP creds (see login flow below).
- `MCP_BEARER_TOKEN` — shared secret; every request needs `Authorization: Bearer <token>`.
- `MCP_PORT` — drives both the in-container listen port and the published host port.
- `MCP_BIND` — host interface the port is published on (`127.0.0.1` = loopback, `0.0.0.0` = LAN).
- `MCP_ALLOWED_HOSTS` — comma-separated Host allow-list for FastMCP's DNS-rebinding protection. **Required when reaching the server over a LAN IP/hostname** (not localhost), else requests get `421 Misdirected Request`. Empty disables the host/origin check (token still enforced).

## Common tasks

Build & (re)deploy after a code change:

```bash
docker compose build mcp-server && docker compose up -d mcp-server
docker compose logs -f mcp-server   # confirm it comes up clean
```

First-time bridge login (interactive — the daemon does the real sync, never let the CLI finish it):

```bash
docker compose run --rm protonmail-bridge bridge --cli
#   > login   (enter Proton email / password / 2FA)
#   > info    (copy username + password into .env)
```

## Deployment

Runs in production on LAN host **`10.10.1.224`**, port **`8088`** (`MCP_BIND=0.0.0.0`). The compose
`restart: unless-stopped` means a server that throws at import will **crash-loop** (port goes
connection-refused) rather than staying up — always tail logs after a deploy.

## Testing the live server

The bridge's IMAP/SMTP ports aren't exposed, so you can't drive `mail.py` locally against real mail;
test through the MCP HTTP endpoint instead. Notes for an MCP client:

- Endpoint is `http://<host>:<port>/mcp/` — **the trailing slash matters**; `/mcp` returns `307` to `/mcp/`.
- Send `Accept: application/json, text/event-stream`; responses come back as SSE frames (`data:` lines).
- The server runs **stateless HTTP** (see below): no `Mcp-Session-Id` to track — each request is self-contained.

## Gotchas (learned the hard way)

- **`stateless_http` placement.** The installed FastMCP does **not** accept `stateless_http` as a
  `FastMCP()` constructor kwarg (raises `TypeError` at import → crash-loop). Pass it in the
  `mcp.run(transport="http", ..., stateless_http=True)` kwargs instead (or `FASTMCP_STATELESS_HTTP`).
  This server is pure request/response tools (no subscriptions/sampling/`listChanged` streaming), so
  stateless is the right mode.
- **Lone UTF-16 surrogates.** Proton Bridge / `imap_tools` decode some headers and bodies with the
  `surrogateescape` handler (or a mis-declared charset), leaving lone surrogate code points that can't
  be UTF-8/JSON encoded — this crashes FastMCP serialization with
  `PydanticSerializationError → UnicodeEncodeError: surrogates not allowed`. `mail.py` runs every
  bridge-decoded return value through `_json_safe()` to replace them. **Any new tool that returns
  bridge-decoded strings must wrap its return in `_json_safe(...)`.**
- **Self-signed bridge cert.** `mail.py` intentionally disables TLS verification for the bridge link
  (`_ssl_context()` sets `CERT_NONE`) — the link is container-to-container on a private network.

## Security

- The bearer token currently travels over **plain HTTP**. On a LAN IP that's cleartext-sniffable.
  A TLS reverse proxy (Caddy/Traefik) in front is the recommended fix and is **not yet in place**.
