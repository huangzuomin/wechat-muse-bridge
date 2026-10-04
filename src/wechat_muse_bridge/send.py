"""Outbound leg: push a Muse reply back to WeChat via iLink sendmessage.

Usage:
    wechat-muse-send [--to-user-id ID] [--context-token TOKEN] [TEXT | -]

TEXT may be given as trailing arguments, or "-" / omitted to read from stdin.
Recipient and context token default to the most recent inbound sender recorded
in the bridge state file (captured by the inbound loop on every message).

Exit codes: 0 sent, 1 failed, 2 usage/config error.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from .config import Config
from .ilink.client import ILinkClient
from .ilink.models import AuthExpired, Credentials, ILinkError
from .state import BridgeState

log = logging.getLogger("wechat_muse_bridge.send")

# Muse chat widgets have no WeChat rendering; strip them rather than leaking markup.
WIDGET_TOKEN_RE = re.compile(r"\[\[hatch_widget:[^\]]*\]\]")
MAX_SEND_CHARS = 4000


def clean_text(text: str) -> str:
    text = WIDGET_TOKEN_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, limit: int = MAX_SEND_CHARS) -> list[str]:
    """Split on paragraph boundaries so no chunk exceeds the WeChat size limit."""
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        while len(para) > limit:
            chunks.append(para[:limit])
            para = para[limit:]
        buf = para
    if buf:
        chunks.append(buf)
    return chunks or [""]


def load_credentials(path: Path) -> Credentials:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"credentials file not found: {path}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read credentials file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("credentials file must contain a JSON object")
    return Credentials.from_dict(raw)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    to_user_id = ""
    context_token = ""
    text_parts: list[str] = []
    read_stdin = False
    i = 0
    while i < len(args):
        if args[i] == "--to-user-id" and i + 1 < len(args):
            to_user_id = args[i + 1]
            i += 2
        elif args[i] == "--context-token" and i + 1 < len(args):
            context_token = args[i + 1]
            i += 2
        elif args[i] == "-":
            read_stdin = True
            i += 1
        elif args[i].startswith("--"):
            print(f"Unknown option: {args[i]}", file=sys.stderr)
            print(__doc__, file=sys.stderr)
            return 2
        else:
            text_parts.append(args[i])
            i += 1
    if read_stdin or (not text_parts and not sys.stdin.isatty()):
        text_parts.append(sys.stdin.read())

    try:
        config = Config.from_env(require_allowlist=False)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        state = BridgeState.load(config.state_path)
        credentials = load_credentials(config.credentials_path)
    except (OSError, RuntimeError) as exc:
        log.error("event=send_failed; reason=%s", exc)
        return 1

    to_user_id = to_user_id or state.reply_to_user_id
    context_token = context_token or state.reply_context_token
    if not to_user_id or not context_token:
        log.error(
            "event=send_failed; reason=no_recipient; "
            "need one inbound WeChat message first to capture to_user_id/context_token"
        )
        return 1

    text = clean_text("".join(text_parts))
    if not text:
        log.error("event=send_failed; reason=empty_text")
        return 1
    if len(text) > config.max_message_chars:
        log.error("event=send_failed; reason=too_long; chars=%d", len(text))
        return 1

    chunks = chunk_text(text)
    ilink = ILinkClient(credentials, config.request_timeout_s)
    try:
        for chunk in chunks:
            ilink.send_message(to_user_id, context_token, chunk)
    except AuthExpired as exc:
        log.error("event=send_failed; kind=WEIXIN_AUTH_EXPIRED; detail=%s", exc)
        return 1
    except ILinkError as exc:
        log.error("event=send_failed; kind=%s", exc.__class__.__name__)
        return 1
    finally:
        ilink.close()
    log.info("event=wechat_send; success=true; chars=%d; chunks=%d", len(text), len(chunks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
