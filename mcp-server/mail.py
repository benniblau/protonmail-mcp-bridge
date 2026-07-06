"""IMAP/SMTP access to Proton Mail via the local Proton Bridge.

The bridge speaks STARTTLS on its local IMAP (1143) and SMTP (1025) ports
using a self-signed certificate, so TLS verification is disabled — the link
is container-to-container on a private Docker network.
"""

from __future__ import annotations

import base64
import os
import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import formataddr, getaddresses

from imap_tools import AND, MailBoxStartTls, MailMessageFlags

BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "protonmail-bridge")
BRIDGE_IMAP_PORT = int(os.environ.get("BRIDGE_IMAP_PORT", "1143"))
BRIDGE_SMTP_PORT = int(os.environ.get("BRIDGE_SMTP_PORT", "1025"))
BRIDGE_USERNAME = os.environ.get("BRIDGE_USERNAME", "")
BRIDGE_PASSWORD = os.environ.get("BRIDGE_PASSWORD", "")


def _ssl_context() -> ssl.SSLContext:
    """TLS context that trusts the bridge's self-signed certificate."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@contextmanager
def _imap(folder: str = "INBOX"):
    """Yield a logged-in IMAP mailbox positioned on `folder`."""
    if not BRIDGE_USERNAME or not BRIDGE_PASSWORD:
        raise RuntimeError(
            "BRIDGE_USERNAME / BRIDGE_PASSWORD are not set. Run the bridge "
            "login (`docker compose run --rm protonmail-bridge bridge --cli`, "
            "then `info`) and put the credentials in .env."
        )
    box = MailBoxStartTls(BRIDGE_HOST, BRIDGE_IMAP_PORT, ssl_context=_ssl_context())
    with box.login(BRIDGE_USERNAME, BRIDGE_PASSWORD, initial_folder=folder) as mb:
        yield mb


def _summary(msg) -> dict:
    return {
        "uid": msg.uid,
        "subject": msg.subject,
        "from": msg.from_,
        "to": list(msg.to),
        "cc": list(msg.cc),
        "date": msg.date_str,
        "flags": list(msg.flags),
        "seen": MailMessageFlags.SEEN in msg.flags,
        "has_attachments": bool(msg.attachments),
        "size": msg.size,
    }


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def list_folders() -> list[dict]:
    with _imap() as mb:
        return [{"name": f.name, "flags": list(f.flags)} for f in mb.folder.list()]


def search_messages(
    folder: str = "INBOX",
    query: str | None = None,
    limit: int = 20,
    unseen_only: bool = False,
) -> list[dict]:
    """List message summaries, newest first.

    `query` is matched as free text across the whole message (IMAP TEXT).
    """
    criteria = "ALL"
    kwargs: dict = {}
    if query:
        kwargs["text"] = query
    if unseen_only:
        kwargs["seen"] = False
    if kwargs:
        criteria = AND(**kwargs)

    with _imap(folder) as mb:
        msgs = mb.fetch(
            criteria,
            limit=limit,
            reverse=True,
            mark_seen=False,
            headers_only=True,
            bulk=True,
        )
        return [_summary(m) for m in msgs]


def _fetch_one(mb, uid: str):
    msgs = list(mb.fetch(AND(uid=uid), mark_seen=False, bulk=True))
    if not msgs:
        raise ValueError(f"No message with uid {uid} in this folder")
    return msgs[0]


def get_message(uid: str, folder: str = "INBOX") -> dict:
    with _imap(folder) as mb:
        m = _fetch_one(mb, uid)
        return {
            **_summary(m),
            "reply_to": list(m.reply_to),
            "bcc": list(m.bcc),
            "text": m.text,
            "html": m.html,
            "headers": {k: list(v) for k, v in m.headers.items()},
            "attachments": [
                {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size": a.size,
                }
                for a in m.attachments
            ],
        }


def get_attachment(uid: str, filename: str, folder: str = "INBOX") -> dict:
    with _imap(folder) as mb:
        m = _fetch_one(mb, uid)
        for a in m.attachments:
            if a.filename == filename:
                return {
                    "filename": a.filename,
                    "content_type": a.content_type,
                    "size": a.size,
                    "content_base64": base64.b64encode(a.payload).decode("ascii"),
                }
        raise ValueError(f"No attachment named {filename!r} on message {uid}")


# --------------------------------------------------------------------------- #
# Write — send
# --------------------------------------------------------------------------- #
def _build_message(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: str | None = None,
    attachments: list[dict] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(("", BRIDGE_USERNAME))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    for att in attachments or []:
        payload = base64.b64decode(att["content_base64"])
        maintype, _, subtype = att.get("content_type", "application/octet-stream").partition("/")
        msg.add_attachment(
            payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att["filename"],
        )
    return msg


def _smtp_send(msg: EmailMessage, recipients: list[str]) -> None:
    with smtplib.SMTP(BRIDGE_HOST, BRIDGE_SMTP_PORT) as smtp:
        smtp.starttls(context=_ssl_context())
        smtp.login(BRIDGE_USERNAME, BRIDGE_PASSWORD)
        smtp.send_message(msg, from_addr=BRIDGE_USERNAME, to_addrs=recipients)


def send_message(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """Send a new email. `attachments` items: {filename, content_base64, content_type?}."""
    msg = _build_message(to, subject, body, cc, bcc, html, attachments)
    recipients = list(to) + list(cc or []) + list(bcc or [])
    _smtp_send(msg, recipients)
    return {"sent": True, "to": recipients, "subject": subject}


def _reply_prefixed(subject: str, prefix: str) -> str:
    return subject if subject.lower().startswith(prefix.lower()) else f"{prefix} {subject}"


def reply_message(
    uid: str,
    body: str,
    folder: str = "INBOX",
    reply_all: bool = False,
    html: str | None = None,
    attachments: list[dict] | None = None,
) -> dict:
    """Reply to a message, preserving threading headers."""
    with _imap(folder) as mb:
        orig = _fetch_one(mb, uid)
    orig_from = [addr for _, addr in getaddresses([orig.from_]) if addr]
    to = orig_from
    cc = None
    if reply_all:
        extra = [addr for _, addr in getaddresses(list(orig.to) + list(orig.cc)) if addr]
        cc = [a for a in extra if a and a != BRIDGE_USERNAME and a not in to]

    msg_id = orig.headers.get("message-id", (None,))[0]
    refs = orig.headers.get("references", (None,))[0]
    references = " ".join(x for x in [refs, msg_id] if x) or None

    msg = _build_message(
        to,
        _reply_prefixed(orig.subject, "Re:"),
        body,
        cc=cc,
        html=html,
        attachments=attachments,
        in_reply_to=msg_id,
        references=references,
    )
    recipients = to + (cc or [])
    _smtp_send(msg, recipients)
    return {"sent": True, "to": recipients, "subject": msg["Subject"]}


def forward_message(
    uid: str,
    to: list[str],
    folder: str = "INBOX",
    body: str = "",
    html: str | None = None,
) -> dict:
    """Forward a message's body to new recipients."""
    with _imap(folder) as mb:
        orig = _fetch_one(mb, uid)
    quoted = (
        f"{body}\n\n---------- Forwarded message ----------\n"
        f"From: {orig.from_}\nDate: {orig.date_str}\nSubject: {orig.subject}\n"
        f"To: {', '.join(orig.to)}\n\n{orig.text or ''}"
    )
    msg = _build_message(to, _reply_prefixed(orig.subject, "Fwd:"), quoted, html=html)
    _smtp_send(msg, list(to))
    return {"sent": True, "to": list(to), "subject": msg["Subject"]}


# --------------------------------------------------------------------------- #
# Write — mutate existing mail
# --------------------------------------------------------------------------- #
def mark_read(uid: str, folder: str = "INBOX", read: bool = True) -> dict:
    with _imap(folder) as mb:
        mb.flag(uid, MailMessageFlags.SEEN, read)
    return {"uid": uid, "seen": read}


def flag_message(uid: str, folder: str = "INBOX", flagged: bool = True) -> dict:
    with _imap(folder) as mb:
        mb.flag(uid, MailMessageFlags.FLAGGED, flagged)
    return {"uid": uid, "flagged": flagged}


def move_message(uid: str, to_folder: str, folder: str = "INBOX") -> dict:
    with _imap(folder) as mb:
        mb.move(uid, to_folder)
    return {"uid": uid, "moved_to": to_folder}


def delete_message(uid: str, folder: str = "INBOX") -> dict:
    with _imap(folder) as mb:
        mb.delete(uid)
    return {"uid": uid, "deleted": True}
