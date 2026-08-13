"""
Google Workspace mail over IMAP, plus sending over SMTP.

IMAP rather than the Gmail API on purpose: an app password takes two minutes to
create, where the API route means creating a Google Cloud project, enabling an
API, configuring an OAuth consent screen and handling a browser redirect. This
does the same job for reading, searching and drafting.

Sending is deliberately awkward. Nothing leaves the machine without the user
saying yes out loud, and the default is to save a draft instead.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Iterator

from ..config import Config
from .registry import Tool

IMAP_TIMEOUT = 30


class MailError(Exception):
    pass


# -- connection --------------------------------------------------------


def _connect(cfg: Config) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(cfg.gmail_imap_host, 993, timeout=IMAP_TIMEOUT)
    except OSError as exc:
        raise MailError(
            f"Could not reach {cfg.gmail_imap_host}. Check the internet connection."
        ) from exc

    try:
        conn.login(cfg.gmail_address, cfg.gmail_app_password)
    except imaplib.IMAP4.error as exc:
        raise MailError(
            "The mail server rejected the login. The app password is probably "
            "wrong, or IMAP is switched off for this Workspace account."
        ) from exc
    return conn


def _decode(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return raw.strip()


def _body_of(msg: email.message.Message, limit: int = 4000) -> str:
    """Plain text if there is any, otherwise HTML with the tags stripped."""
    plain, html = "", ""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = text

    text = plain or re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return text[:limit]


def _summarise(msg: email.message.Message, index: int, with_body: bool) -> str:
    when = _decode(msg.get("Date"))
    try:
        parsed = email.utils.parsedate_to_datetime(msg.get("Date"))
        when = parsed.strftime("%a %d %b, %H:%M")
    except Exception:
        pass

    lines = [
        f"[{index}] From: {_decode(msg.get('From'))}",
        f"    Subject: {_decode(msg.get('Subject')) or '(no subject)'}",
        f"    Date: {when}",
    ]
    if with_body:
        body = _body_of(msg)
        lines.append(f"    Body: {body if body else '(empty)'}")
    return "\n".join(lines)


def _search(conn: imaplib.IMAP4_SSL, criteria: list[str]) -> list[bytes]:
    typ, data = conn.search(None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _fetch(conn: imaplib.IMAP4_SSL, uid: bytes) -> email.message.Message | None:
    # BODY.PEEK leaves the unread flag alone. Reading the user's mail should
    # not silently mark it read behind them.
    typ, data = conn.fetch(uid, "(BODY.PEEK[])")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    return email.message_from_bytes(data[0][1])


# -- the tools ---------------------------------------------------------


def tools(cfg: Config) -> list[Tool]:
    def check_inbox(args: dict) -> str:
        hours = int(args.get("hours", 24))
        unread_only = bool(args.get("unread_only", False))
        limit = max(1, min(int(args.get("limit", 10)), 25))

        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%d-%b-%Y")
        criteria = ["SINCE", since]
        if unread_only:
            criteria = ["UNSEEN"] + criteria

        conn = _connect(cfg)
        try:
            conn.select("INBOX", readonly=True)
            uids = _search(conn, criteria)
            if not uids:
                window = "unread " if unread_only else ""
                return f"No {window}mail in the last {hours} hours."
            picked = uids[-limit:][::-1]
            out = [f"{len(uids)} message(s); showing the {len(picked)} most recent."]
            for i, uid in enumerate(picked, 1):
                msg = _fetch(conn, uid)
                if msg:
                    out.append(_summarise(msg, i, with_body=False))
            return "\n".join(out)
        finally:
            _close(conn)

    def search_mail(args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "No search text was given."
        field = str(args.get("field", "text")).upper()
        if field not in ("FROM", "SUBJECT", "TEXT", "TO"):
            field = "TEXT"
        limit = max(1, min(int(args.get("limit", 5)), 15))

        conn = _connect(cfg)
        try:
            conn.select("INBOX", readonly=True)
            uids = _search(conn, [field, f'"{query}"'])
            if not uids:
                return f"Nothing in the inbox matching {query!r}."
            picked = uids[-limit:][::-1]
            out = [f"{len(uids)} match(es); showing {len(picked)}."]
            for i, uid in enumerate(picked, 1):
                msg = _fetch(conn, uid)
                if msg:
                    out.append(_summarise(msg, i, with_body=False))
            return "\n".join(out)
        finally:
            _close(conn)

    def read_message(args: dict) -> str:
        """Read one message in full, identified by a search that finds it."""
        query = str(args.get("query", "")).strip()
        field = str(args.get("field", "subject")).upper()
        if field not in ("FROM", "SUBJECT", "TEXT", "TO"):
            field = "SUBJECT"
        if not query:
            return "No search text was given."

        conn = _connect(cfg)
        try:
            conn.select("INBOX", readonly=True)
            uids = _search(conn, [field, f'"{query}"'])
            if not uids:
                return f"No message found matching {query!r}."
            msg = _fetch(conn, uids[-1])
            if msg is None:
                return "The message could not be downloaded."
            return _summarise(msg, 1, with_body=True)
        finally:
            _close(conn)

    def draft_reply(args: dict) -> str:
        """
        Write a message into the Drafts folder. Nothing is sent.

        This is the default way the assistant produces email. It means a
        misheard instruction costs the user a stray draft, not a sent message.
        """
        to = str(args.get("to", "")).strip()
        subject = str(args.get("subject", "")).strip()
        body = str(args.get("body", "")).strip()
        if not (to and body):
            return "A recipient and a body are both needed."

        msg = EmailMessage()
        msg["From"] = cfg.gmail_address
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(body)

        conn = _connect(cfg)
        try:
            folder = _drafts_folder(conn)
            conn.append(folder, "\\Draft", imaplib.Time2Internaldate(datetime.now()), msg.as_bytes())
            return (
                f"Saved a draft to {to} with the subject {msg['Subject']!r}. "
                "It has not been sent."
            )
        finally:
            _close(conn)

    def send_mail(args: dict) -> str:
        to = str(args.get("to", "")).strip()
        subject = str(args.get("subject", "")).strip()
        body = str(args.get("body", "")).strip()
        if not (to and body):
            return "A recipient and a body are both needed."

        msg = EmailMessage()
        msg["From"] = cfg.gmail_address
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"
        msg.set_content(body)

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=IMAP_TIMEOUT) as s:
                s.login(cfg.gmail_address, cfg.gmail_app_password)
                s.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError("The mail server rejected the login when sending.") from exc
        except OSError as exc:
            raise MailError("Could not reach the outgoing mail server.") from exc
        return f"Sent to {to}."

    return [
        Tool(
            name="check_inbox",
            description=(
                "Look at recent mail in the user's inbox. Returns senders, subjects "
                "and dates, not full bodies. Use this for questions like 'what came "
                "in overnight' or 'anything new'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "How far back to look. 24 for today, 168 for a week.",
                    },
                    "unread_only": {"type": "boolean"},
                    "limit": {"type": "integer", "description": "Max messages, up to 25."},
                },
            },
            run=check_inbox,
        ),
        Tool(
            name="search_mail",
            description=(
                "Search the inbox. Use field 'from' for a person, 'subject' for a "
                "topic, 'text' to search everywhere."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "field": {"type": "string", "enum": ["from", "subject", "text", "to"]},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            run=search_mail,
        ),
        Tool(
            name="read_message",
            description=(
                "Read one message in full, including its body. Find it with the same "
                "search terms as search_mail; the most recent match is returned."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "field": {"type": "string", "enum": ["from", "subject", "text", "to"]},
                },
                "required": ["query"],
            },
            run=read_message,
        ),
        Tool(
            name="draft_reply",
            description=(
                "Save an email as a draft in the user's Drafts folder without sending "
                "it. Prefer this over send_mail. The user can review it in Gmail."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "body"],
            },
            run=draft_reply,
        ),
        Tool(
            name="send_mail",
            description=(
                "Send an email immediately. This cannot be undone, so only use it "
                "when the user has clearly asked to send rather than draft."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "body"],
            },
            run=send_mail,
            needs_confirmation=cfg.send_email_needs_confirmation,
            confirm_template="Send this email to {to}?",
        ),
    ]


def _drafts_folder(conn: imaplib.IMAP4_SSL) -> str:
    """
    Find the Drafts folder.

    Gmail localises it -- a French account has [Gmail]/Brouillons -- so the
    English name is a fallback, not the answer. The \\Drafts special-use flag
    is the reliable way to find it.
    """
    typ, data = conn.list()
    if typ == "OK":
        for line in data or []:
            text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            if "\\Drafts" in text:
                match = re.search(r'"([^"]+)"\s*$', text.strip())
                if match:
                    return f'"{match.group(1)}"'
    return '"[Gmail]/Drafts"'


def _close(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.close()
    except Exception:
        pass
    try:
        conn.logout()
    except Exception:
        pass


def selftest(cfg: Config) -> tuple[bool, str]:
    """Used by check.bat: prove the credentials work before the user relies on them."""
    try:
        conn = _connect(cfg)
    except MailError as exc:
        return False, str(exc)
    try:
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            return False, "Logged in, but the inbox could not be opened."
        return True, f"Connected to {cfg.gmail_address}."
    finally:
        _close(conn)
