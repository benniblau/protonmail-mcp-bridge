# Proton Mail Bridge + Streamable MCP Server

A self-contained Docker Compose stack that:

1. Builds the **official [Proton Mail Bridge](https://github.com/ProtonMail/proton-bridge)** from source and runs it **headless** (`--noninteractive`), exposing your Proton Mail account over local IMAP/SMTP.
2. Runs a **Python + [FastMCP](https://gofastmcp.com) MCP server** over **streamable HTTP** with **bearer-token auth**, exposing full read + write mail tools.

```
MCP client ──HTTP + Bearer──▶ mcp-server ──IMAP 1143 / SMTP 1025 (STARTTLS)──▶ protonmail-bridge ──▶ Proton
  127.0.0.1:8080                                        (private "mailnet" network)
```

The MCP endpoint is published on `127.0.0.1:8080` only. Over the loopback/LAN, a bearer token over plain HTTP is acceptable.

## Prerequisites

- Docker + Docker Compose
- A Proton Mail account on a paid plan (Bridge requires Mail Plus / Unlimited / Business)

## Setup

### 1. Configure environment

```bash
cp .env.example .env
# generate a strong MCP token:
openssl rand -hex 32          # paste into MCP_BEARER_TOKEN in .env
```

### 2. Build the images

```bash
docker compose build
```

This compiles the official bridge (`make build-nogui`, Go 1.26) from the tag pinned in `docker-compose.yml` (`BRIDGE_TAG`), patched to bind `0.0.0.0` so the MCP container can reach it.

### 3. Log in to Proton Bridge (one-time, interactive)

```bash
docker compose run --rm protonmail-bridge bridge --cli
```

At the prompt:

```
>>> login          # enter your Proton email, password, and 2FA
>>> info           # copy the shown IMAP/SMTP username and password
>>> exit
```

The entrypoint sets up the gpg/`pass` keychain automatically before the CLI starts. The login is stored in the `protonmail` volume and survives restarts.

Put the credentials from `info` into `.env`:

```
BRIDGE_USERNAME=<username from info>
BRIDGE_PASSWORD=<password from info>
```

### 4. Start the stack

```bash
docker compose up -d
docker compose logs -f            # bridge: IMAP/SMTP on 0.0.0.0; mcp-server: serving on :8080
```

## Using the MCP server

Endpoint: `http://127.0.0.1:8080/mcp/` — send `Authorization: Bearer <MCP_BEARER_TOKEN>`.

Quick check with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP
# URL:       http://127.0.0.1:8080/mcp/
# Header:    Authorization: Bearer <your MCP_BEARER_TOKEN>
```

### Example: Claude Code / MCP client config

```json
{
  "mcpServers": {
    "protonmail": {
      "type": "http",
      "url": "http://127.0.0.1:8080/mcp/",
      "headers": { "Authorization": "Bearer <your MCP_BEARER_TOKEN>" }
    }
  }
}
```

## Tools

| Tool | Purpose |
| --- | --- |
| `list_folders` | List all folders/labels |
| `search_messages` | Search a folder (free-text `query`, `unseen_only`, `limit`); returns summaries with `uid` |
| `get_message` | Full message: text, html, headers, attachment list |
| `get_attachment` | One attachment's bytes as base64 |
| `send_message` | Send new mail (to/cc/bcc, html, attachments) |
| `reply_message` | Reply (threading preserved; `reply_all`) |
| `forward_message` | Forward to new recipients |
| `mark_read` | Mark read/unread |
| `flag_message` | Star/flag or unflag |
| `move_message` | Move to another folder |
| `delete_message` | Delete a message |

## Notes

- **Credential rotation:** re-running the bridge login regenerates the IMAP/SMTP password. Update `.env` and `docker compose up -d --force-recreate mcp-server`.
- **Self-signed TLS:** the bridge uses a self-signed cert on its local STARTTLS ports; the MCP server intentionally skips verification on this private link.
- **Bump the bridge:** change `BRIDGE_TAG` in `docker-compose.yml` and `docker compose build --no-cache protonmail-bridge`.
- `.env` holds real secrets and is gitignored.
