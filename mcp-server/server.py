"""Streamable-HTTP MCP server exposing Proton Mail (via Proton Bridge).

Auth: a single static bearer token read from MCP_BEARER_TOKEN. All requests
must send `Authorization: Bearer <token>`. Intended for localhost/LAN use.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

import mail

MCP_BEARER_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8080"))

if not MCP_BEARER_TOKEN:
    raise SystemExit("MCP_BEARER_TOKEN must be set (see .env).")

verifier = StaticTokenVerifier(
    tokens={
        MCP_BEARER_TOKEN: {
            "client_id": "protonmail-mcp",
            "scopes": ["mail:read", "mail:write"],
        }
    }
)

mcp = FastMCP(name="protonmail-mcp", auth=verifier)


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #
@mcp.tool
def list_folders() -> list[dict]:
    """List all mailbox folders (INBOX, Sent, Archive, labels, …)."""
    return mail.list_folders()


@mcp.tool
def search_messages(
    folder: str = "INBOX",
    query: str | None = None,
    limit: int = 20,
    unseen_only: bool = False,
) -> list[dict]:
    """Search a folder and return message summaries (newest first).

    `query` is matched as free text across the whole message. Each result
    includes the `uid` needed by the other tools.
    """
    return mail.search_messages(folder=folder, query=query, limit=limit, unseen_only=unseen_only)


@mcp.tool
def get_message(uid: str, folder: str = "INBOX") -> dict:
    """Fetch a single message's full content (text, html, headers, attachment list)."""
    return mail.get_message(uid=uid, folder=folder)


@mcp.tool
def get_attachment(uid: str, filename: str, folder: str = "INBOX") -> dict:
    """Fetch one attachment's bytes as base64 from a message."""
    return mail.get_attachment(uid=uid, filename=filename, folder=folder)


# --------------------------------------------------------------------------- #
# Send tools
# --------------------------------------------------------------------------- #
@mcp.tool
def send_message(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """Send a new email.

    `attachments` items are {filename, content_base64, content_type?}.
    Provide `html` for an HTML alternative body.
    """
    return mail.send_message(
        to=to, subject=subject, body=body, cc=cc, bcc=bcc, html=html, attachments=attachments
    )


@mcp.tool
def reply_message(
    uid: str,
    body: str,
    folder: str = "INBOX",
    reply_all: bool = False,
    html: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """Reply to a message (threading headers preserved). Set reply_all to include Cc."""
    return mail.reply_message(
        uid=uid, body=body, folder=folder, reply_all=reply_all, html=html, attachments=attachments
    )


@mcp.tool
def forward_message(
    uid: str,
    to: list[str],
    folder: str = "INBOX",
    body: str = "",
    html: str | None = None,
) -> dict:
    """Forward a message to new recipients, with an optional leading note."""
    return mail.forward_message(uid=uid, to=to, folder=folder, body=body, html=html)


# --------------------------------------------------------------------------- #
# Mutation tools
# --------------------------------------------------------------------------- #
@mcp.tool
def mark_read(uid: str, folder: str = "INBOX", read: bool = True) -> dict:
    """Mark a message read (read=True) or unread (read=False)."""
    return mail.mark_read(uid=uid, folder=folder, read=read)


@mcp.tool
def flag_message(uid: str, folder: str = "INBOX", flagged: bool = True) -> dict:
    """Star/flag (flagged=True) or unflag a message."""
    return mail.flag_message(uid=uid, folder=folder, flagged=flagged)


@mcp.tool
def move_message(uid: str, to_folder: str, folder: str = "INBOX") -> dict:
    """Move a message from `folder` to `to_folder`."""
    return mail.move_message(uid=uid, to_folder=to_folder, folder=folder)


@mcp.tool
def delete_message(uid: str, folder: str = "INBOX") -> dict:
    """Delete a message (moves to Trash / removes per the server's semantics)."""
    return mail.delete_message(uid=uid, folder=folder)


if __name__ == "__main__":
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)
