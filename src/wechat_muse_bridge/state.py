from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BridgeState:
    cursor: str = ""
    muse_session_id: str = ""
    last_message_id: str = ""
    pending_message_ids: list[str] = field(default_factory=list)
    # Outbound leg: most recent inbound sender, used as the sendmessage target.
    reply_to_user_id: str = ""
    reply_context_token: str = ""

    @classmethod
    def load(cls, path: Path) -> "BridgeState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(muse_session_id=str(uuid.uuid4()))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read state file {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("state file must contain a JSON object")
        return cls(
            cursor=_string(raw, "cursor"),
            muse_session_id=_valid_session(_string(raw, "muse_session_id")),
            last_message_id=_string(raw, "last_message_id"),
            pending_message_ids=_string_list(raw, "pending_message_ids"),
            reply_to_user_id=_string(raw, "reply_to_user_id"),
            reply_context_token=_string(raw, "reply_context_token"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cursor": self.cursor,
            "muse_session_id": self.muse_session_id,
            "last_message_id": self.last_message_id,
            "pending_message_ids": self.pending_message_ids or [],
            "reply_to_user_id": self.reply_to_user_id,
            "reply_context_token": self.reply_context_token,
        }
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
            if os.name == "posix":
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def reset_session(self) -> None:
        self.muse_session_id = str(uuid.uuid4())


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RuntimeError(f"state field {key} must be a string")
    return value


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"state field {key} must be a list of strings")
    return value[-512:]


def _valid_session(value: str) -> str:
    import re

    if re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
        return value
    return str(uuid.uuid4())
