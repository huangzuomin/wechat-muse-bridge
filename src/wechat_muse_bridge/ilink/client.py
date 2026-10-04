from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import AuthExpired, Credentials, NetworkError, ProtocolError, UpdateBatch
from .protocol import common_headers, get_updates_body, send_message_body

log = logging.getLogger(__name__)


class ILinkClient:
    def __init__(self, credentials: Credentials, timeout_s: float = 45.0):
        self.credentials = credentials
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_s))

    def close(self) -> None:
        self.client.close()

    def get_updates(self, cursor: str, poll_timeout_ms: int) -> UpdateBatch:
        try:
            response = self.client.post(
                f"{self.credentials.base_url}/ilink/bot/getupdates",
                headers=common_headers(authenticated=True, bot_token=self.credentials.bot_token),
                json=get_updates_body(cursor, poll_timeout_ms),
                timeout=httpx.Timeout(max(45.0, poll_timeout_ms / 1000 + 10)),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise AuthExpired("iLink rejected the saved credential") from exc
            raise NetworkError(f"getUpdates HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise NetworkError(f"getUpdates request failed: {exc.__class__.__name__}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("getUpdates response must be an object")
        ret = _int(payload.get("ret", 0), "ret")
        errcode = _int(payload.get("errcode", 0), "errcode")
        if ret == -14 or errcode == -14:
            raise AuthExpired("iLink session expired (ret/errcode -14)")
        if ret != 0:
            raise ProtocolError(f"getUpdates returned ret={ret}")
        if errcode != 0:
            raise ProtocolError(f"getUpdates returned errcode={errcode}")
        messages = payload.get("msgs", [])
        new_cursor = payload.get("get_updates_buf", "")
        if not isinstance(messages, list) or not all(isinstance(msg, dict) for msg in messages):
            raise ProtocolError("getUpdates msgs must be a list of objects")
        if not isinstance(new_cursor, str):
            raise ProtocolError("getUpdates get_updates_buf must be a string")
        return UpdateBatch(tuple(messages), new_cursor, ret)


    def send_message(self, to_user_id: str, context_token: str, text: str) -> None:
        """POST /ilink/bot/sendmessage: deliver one text message to a WeChat user.

        Raises AuthExpired when the saved credential is rejected or the
        session timed out, NetworkError on transport failure, ProtocolError
        when the API reports an error.
        """
        body = send_message_body(to_user_id=to_user_id, context_token=context_token, text=text)
        try:
            response = self.client.post(
                f"{self.credentials.base_url}/ilink/bot/sendmessage",
                headers=common_headers(authenticated=True, bot_token=self.credentials.bot_token),
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise AuthExpired("iLink rejected the saved credential") from exc
            raise NetworkError(f"sendMessage HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise NetworkError(f"sendMessage request failed: {exc.__class__.__name__}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("sendMessage response must be an object")
        ret = _int(payload.get("ret", 0), "ret")
        errcode = _int(payload.get("errcode", 0), "errcode")
        if ret == -14 or errcode == -14:
            raise AuthExpired("iLink session expired (ret/errcode -14)") from exc
        if ret != 0 or errcode != 0:
            raise ProtocolError(f"sendMessage returned ret={ret} errcode={errcode}")


def _int(value: Any, name: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"iLink {name} must be an integer")
    return value
