from __future__ import annotations

import subprocess
import time
from collections.abc import Callable


class MuseError(RuntimeError):
    code = "MUSEGADGET_ERROR"


class MuseNotConnected(MuseError):
    code = "MUSE_NOT_CONNECTED"


class MuseClient:
    def __init__(self, command: tuple[str, ...], timeout_s: float = 100.0,
                 runner: Callable = subprocess.run):
        self.command = command
        self.timeout_s = timeout_s
        self.runner = runner

    def send_user_message(self, session_id: str, text: str) -> float:
        started = time.monotonic()
        try:
            result = self.runner(
                [*self.command, "send-user-msg", "--session-id", session_id, "-"],
                input=text,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MuseError("musegadget send-user-msg timed out") from exc
        except OSError as exc:
            raise MuseError(f"cannot execute musegadget: {exc.__class__.__name__}") from exc
        if result.returncode != 0:
            # Do not propagate subprocess output, which may include message text.
            stderr = result.stderr if isinstance(result.stderr, str) else ""
            error = (
                MuseNotConnected
                if result.returncode == 1 and "Could not reach the musegadget service" in stderr
                else MuseError
            )
            raise error(f"musegadget exited with status {result.returncode}")
        return (time.monotonic() - started) * 1000
