from __future__ import annotations

import hashlib
import logging
import random
import time
from collections import deque

from .config import Config
from .ilink.auth import ILinkAuth
from .ilink.client import ILinkClient
from .ilink.models import AuthExpired, Credentials, ILinkError, ProtocolError
from .ilink.protocol import inbound_text
from .muse.client import MuseClient, MuseError, MuseNotConnected
from .state import BridgeState

log = logging.getLogger(__name__)


class Bridge:
    def __init__(self, config: Config, state: BridgeState, ilink: ILinkClient,
                 muse: MuseClient):
        self.config = config
        self.state = state
        self.ilink = ilink
        self.muse = muse
        self.running = True
        initial_ids = list(state.pending_message_ids or [])
        if state.last_message_id:
            initial_ids.append(state.last_message_id)
        self._recent_ids = deque(initial_ids[-512:], maxlen=512)
        self._recent_id_set = set(self._recent_ids)

    @classmethod
    def create(cls, config: Config, state: BridgeState, credentials: Credentials) -> "Bridge":
        return cls(config, state, ILinkClient(credentials, config.request_timeout_s),
                   MuseClient(config.muse_command))

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        backoff = 1
        try:
            while self.running:
                try:
                    batch = self.ilink.get_updates(self.state.cursor, self.config.poll_timeout_ms)
                    backoff = 1
                    for message in batch.messages:
                        if not self.running:
                            break
                        self._process(message)
                    else:
                        previous_cursor = self.state.cursor
                        previous_pending_ids = self.state.pending_message_ids
                        if batch.cursor:
                            self.state.cursor = batch.cursor
                        self.state.pending_message_ids = []
                        try:
                            self.state.save(self.config.state_path)
                        except OSError:
                            self.state.cursor = previous_cursor
                            self.state.pending_message_ids = previous_pending_ids
                            raise
                        self._recent_ids.clear()
                        self._recent_id_set.clear()
                        if self.state.last_message_id:
                            self._remember(self.state.last_message_id)
                        continue
                    # Shutdown during a batch: preserve the prior cursor for safe replay.
                    break
                except AuthExpired:
                    log.error("event=needs_login; iLink credential expired; polling paused")
                    while self.running:
                        time.sleep(1)
                    return
                except (ILinkError, MuseError, OSError) as exc:
                    log.error("event=bridge_error; kind=%s", _error_kind(exc))
                    if self.running:
                        time.sleep(backoff + random.uniform(0, min(0.25, backoff / 4)))
                        backoff = min(30, backoff * 2)
        finally:
            self.ilink.close()

    def process_batch(self, messages: tuple[dict, ...], cursor: str) -> None:
        """Process one batch and commit cursor only after every item is safe."""
        for message in messages:
            self._process(message)
        previous_cursor = self.state.cursor
        previous_pending_ids = self.state.pending_message_ids
        if cursor:
            self.state.cursor = cursor
        self.state.pending_message_ids = []
        try:
            self.state.save(self.config.state_path)
        except OSError:
            self.state.cursor = previous_cursor
            self.state.pending_message_ids = previous_pending_ids
            raise
        self._recent_ids.clear()
        self._recent_id_set.clear()
        if self.state.last_message_id:
            self._remember(self.state.last_message_id)

    def _process(self, message: dict) -> None:
        message_id = str(message.get("message_id") or "")
        if message_id and message_id in self._recent_id_set:
            log.info("event=duplicate; message_id=%s", _safe_id(message_id))
            return
        sender = message.get("from_user_id")
        if not isinstance(sender, str) or not sender:
            log.warning("event=invalid_message; reason=missing_sender; message_id=%s", _safe_id(message_id))
            self._remember(message_id)
            return
        if sender not in self.config.allowed_user_ids:
            log.info("event=unauthorized_sender; sender_hash=%s; message_id=%s",
                     _sender_hash(sender), _safe_id(message_id))
            self._remember(message_id)
            return
        text = inbound_text(message)
        if text is None:
            log.info("event=ignored_message; sender_hash=%s; message_id=%s",
                     _sender_hash(sender), _safe_id(message_id))
            self._remember(message_id)
            return
        if len(text) > self.config.max_message_chars:
            log.warning("event=invalid_message; reason=too_long; chars=%d; message_id=%s",
                        len(text), _safe_id(message_id))
            self._remember(message_id)
            return
        if text == "/reset":
            self.state.reset_session()
            self.state.last_message_id = message_id
            self.state.pending_message_ids = [*(self.state.pending_message_ids or []), message_id][-512:]
            self._remember(message_id)
            self.state.save(self.config.state_path)
            log.info("event=session_reset; sender_hash=%s; message_id=%s",
                     _sender_hash(sender), _safe_id(message_id))
            return
        envelope = f"[via WeChat]\n\n{text}"
        started = time.monotonic()
        self.muse.send_user_message(self.state.muse_session_id, envelope)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self.state.last_message_id = message_id
        self.state.pending_message_ids = [*(self.state.pending_message_ids or []), message_id][-512:]
        self._remember(message_id)
        # Persist delivery progress before advancing the batch cursor.
        self.state.save(self.config.state_path)
        log.info("event=muse_delivery; message_id=%s; success=true; latency_ms=%d; chars=%d",
                 _safe_id(message_id), elapsed_ms, len(text))

    def _remember(self, message_id: str) -> None:
        if not message_id:
            return
        if len(self._recent_ids) == self._recent_ids.maxlen:
            removed = self._recent_ids[0]
            self._recent_id_set.discard(removed)
        self._recent_ids.append(message_id)
        self._recent_id_set.add(message_id)


def _sender_hash(sender: str) -> str:
    return hashlib.sha256(sender.encode()).hexdigest()[:12]


def _safe_id(message_id: str) -> str:
    if not message_id:
        return "unknown"
    return "".join(char for char in message_id[:64] if char.isalnum() or char in "-_") or "invalid"


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, MuseNotConnected):
        return "MUSE_NOT_CONNECTED"
    if isinstance(exc, MuseError):
        return "MUSEGADGET_ERROR"
    if isinstance(exc, AuthExpired):
        return "WEIXIN_AUTH_EXPIRED"
    if isinstance(exc, ProtocolError):
        return "WEIXIN_PROTOCOL_ERROR"
    if isinstance(exc, ILinkError):
        return "WEIXIN_NETWORK_ERROR"
    return "STATE_ERROR"
