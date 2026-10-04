"""Tencent openclaw-weixin protocol baseline: commit 24de5c9eb0dd."""

from __future__ import annotations

import base64
import secrets

CHANNEL_VERSION = "2.4.8"
BOT_TYPE = 3


def common_headers(*, authenticated: bool, bot_token: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "iLink-App-Id": "bot",
        # Upstream encodes a 2.4.8 client version as hex 0x00020808, decimal string.
        "iLink-App-ClientVersion": str(int("0x00020408", 16)),
        "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode(),
    }
    if authenticated:
        headers["AuthorizationType"] = "ilink_bot_token"
        headers["Authorization"] = f"Bearer {bot_token}"
    return headers


def base_info() -> dict[str, str]:
    return {"channel_version": CHANNEL_VERSION, "bot_agent": "wechat-muse-bridge"}


def get_updates_body(cursor: str, poll_timeout_ms: int) -> dict:
    return {
        "get_updates_buf": cursor,
        "longpolling_timeout_ms": poll_timeout_ms,
        "base_info": base_info(),
    }


def inbound_text(message: dict) -> str | None:
    """Extract supported direct-chat text only; unknown protocol shapes are ignored."""
    if message.get("message_type") != 1:
        return None
    if message.get("group_id"):
        return None
    items = message.get("item_list")
    if not isinstance(items, list):
        return None
    chunks: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != 1:
            continue
        text_item = item.get("text_item")
        if isinstance(text_item, dict) and isinstance(text_item.get("text"), str):
            chunks.append(text_item["text"])
    text = "".join(chunks).strip()
    return text or None


def new_client_id() -> str:
    """Client-generated outbound message id, format hl-<12 hex chars>."""
    return "hl-" + secrets.token_hex(6)


def send_message_body(*, to_user_id: str, context_token: str, text: str) -> dict:
    """Build the POST /ilink/bot/sendmessage JSON body for a text message."""
    return {
        "msg": {
            "to_user_id": to_user_id,
            "client_id": new_client_id(),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        },
        "base_info": base_info(),
    }
