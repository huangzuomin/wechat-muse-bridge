from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ILinkError(RuntimeError):
    """Base class for iLink failures."""


class AuthExpired(ILinkError):
    """The account must be authenticated again."""


class ProtocolError(ILinkError):
    """Tencent returned an invalid or unsupported response."""


class NetworkError(ILinkError):
    """An iLink request failed at the transport layer."""


@dataclass(frozen=True)
class Credentials:
    bot_token: str
    bot_id: str
    base_url: str
    ilink_user_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Credentials":
        token = data.get("bot_token")
        bot_id = data.get("bot_id")
        base_url = data.get("base_url")
        if not all(isinstance(value, str) and value for value in (token, bot_id, base_url)):
            raise ProtocolError("credential file is missing required fields")
        if not base_url.startswith("https://"):
            raise ProtocolError("credential API base URL must use HTTPS")
        return cls(token, bot_id, base_url.rstrip("/"), str(data.get("ilink_user_id") or ""))

    def to_dict(self) -> dict[str, str]:
        return {
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "base_url": self.base_url,
            "ilink_user_id": self.ilink_user_id,
        }


@dataclass(frozen=True)
class UpdateBatch:
    messages: tuple[dict[str, Any], ...]
    cursor: str
    ret: int
