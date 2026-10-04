from __future__ import annotations

import os
import shlex
from urllib.parse import urlsplit
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    allowed_user_ids: frozenset[str]
    muse_command: tuple[str, ...]
    max_message_chars: int = 8000
    api_base_url: str = "https://ilinkai.weixin.qq.com"
    poll_timeout_ms: int = 35000
    request_timeout_s: float = 45.0
    log_level: str = "INFO"
    debug_payloads: bool = False

    @property
    def credentials_path(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @classmethod
    def from_env(cls, *, require_allowlist: bool = True) -> "Config":
        allowed = frozenset(
            part.strip() for part in os.environ.get("ALLOWED_USER_IDS", "").split(",")
            if part.strip()
        )
        if require_allowlist and not allowed:
            raise ValueError("ALLOWED_USER_IDS must contain at least one sender ID")
        try:
            max_chars = int(os.environ.get("MAX_MESSAGE_CHARS", "8000"))
            poll_ms = int(os.environ.get("ILINK_POLL_TIMEOUT_MS", "35000"))
            timeout_s = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "45"))
        except ValueError as exc:
            raise ValueError("message, poll, and timeout limits must be numeric") from exc
        if max_chars < 1 or not 1000 <= poll_ms <= 60000 or timeout_s <= 0:
            raise ValueError("invalid message, poll, or HTTP timeout limit")
        command = tuple(shlex.split(os.environ.get("MUSEGADGET_COMMAND", "musegadget")))
        if not command:
            raise ValueError("MUSEGADGET_COMMAND must not be empty")
        api_base_url = os.environ.get("ILINK_API_BASE_URL", "https://ilinkai.weixin.qq.com").rstrip("/")
        parsed_api_url = urlsplit(api_base_url)
        if parsed_api_url.scheme != "https" or not parsed_api_url.hostname:
            raise ValueError("ILINK_API_BASE_URL must be an HTTPS URL with a hostname")
        return cls(
            data_dir=Path(os.environ.get("WECHAT_MUSE_DATA_DIR", "/var/lib/wechat-muse-bridge")),
            allowed_user_ids=allowed,
            muse_command=command,
            max_message_chars=max_chars,
            api_base_url=api_base_url,
            poll_timeout_ms=poll_ms,
            request_timeout_s=timeout_s,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            debug_payloads=os.environ.get("DEBUG_PAYLOADS", "false").lower() == "true",
        )
