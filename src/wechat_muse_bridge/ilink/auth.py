from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote

import qrcode

from .models import AuthExpired, Credentials, NetworkError, ProtocolError
from .protocol import BOT_TYPE, common_headers

log = logging.getLogger(__name__)


class ILinkAuth:
    def __init__(self, client, api_base_url: str):
        self.client = client
        self.api_base_url = api_base_url.rstrip("/")

    def login(self) -> Credentials:
        try:
            response = self.client.post(
                f"{self.api_base_url}/ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}",
                headers=common_headers(authenticated=False),
                json={"local_token_list": []},
            )
            response.raise_for_status()
            payload = response.json()
            qr_url = payload.get("qrcode")
            if not isinstance(qr_url, str) or not qr_url:
                raise ProtocolError("QR login response did not include qrcode")
            qr_content = payload.get("qrcode_img_content") or qr_url
            if not isinstance(qr_content, str):
                raise ProtocolError("QR login qrcode_img_content must be text")
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_content)
            qr.print_ascii(invert=True)
            print("Scan this QR code with WeChat to log in.")
            return self._wait_for_confirmation(qr_url)
        except ProtocolError:
            raise
        except Exception as exc:
            raise NetworkError(f"QR login request failed: {exc.__class__.__name__}") from exc

    def _wait_for_confirmation(self, qr_url: str) -> Credentials:
        deadline = time.monotonic() + 600
        verify_code = ""
        while time.monotonic() < deadline:
            url = f"{self.api_base_url}/ilink/bot/get_qrcode_status?qrcode={quote(qr_url, safe='')}"
            if verify_code:
                url += f"&verify_code={quote(verify_code, safe='')}"
            try:
                response = self.client.get(url, headers={"Content-Type": "application/json"})
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                raise NetworkError(f"QR status request failed: {exc.__class__.__name__}") from exc
            if not isinstance(payload, dict):
                raise ProtocolError("QR status response must be an object")
            status = payload.get("status")
            if status == "confirmed":
                try:
                    return Credentials.from_dict({
                        "bot_token": payload["bot_token"],
                        "bot_id": payload["ilink_bot_id"],
                        "base_url": payload["baseurl"],
                        "ilink_user_id": payload.get("ilink_user_id", ""),
                    })
                except (KeyError, TypeError) as exc:
                    raise ProtocolError("confirmed QR response is missing credentials") from exc
            if status in {"expired", "verify_code_blocked"}:
                raise AuthExpired(f"QR login ended with status {status}")
            if status == "need_verifycode":
                verify_code = input("WeChat verification code: ").strip()
                continue
            if status not in {"wait", "scaned", "scaned_but_redirect", "binded_redirect"}:
                raise ProtocolError(f"unknown QR login status: {status!r}")
            time.sleep(1)
        raise AuthExpired("QR login timed out after 10 minutes")
