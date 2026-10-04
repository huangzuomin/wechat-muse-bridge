from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import sys
import time
from pathlib import Path

import httpx

from .bridge import Bridge
from .config import Config
from .ilink.auth import ILinkAuth
from .ilink.client import ILinkClient
from .ilink.models import AuthExpired, Credentials, ILinkError
from .ilink.protocol import inbound_text
from .muse.client import MuseClient
from .state import BridgeState

log = logging.getLogger("wechat_muse_bridge")


def load_credentials(path: Path) -> Credentials | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read credentials file {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("credentials file must contain a JSON object")
    return Credentials.from_dict(raw)


def save_credentials(path: Path, credentials: Credentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    fd = None
    try:
        import os

        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump(credentials.to_dict(), stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
        if os.name == "posix":
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except BaseException:
        if fd is not None:
            import os
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def obtain_credentials(config: Config) -> Credentials:
    existing = load_credentials(config.credentials_path)
    if existing:
        return existing
    log.info("event=needs_login; start QR login")
    with httpx.Client(timeout=config.request_timeout_s) as client:
        credentials = ILinkAuth(client, config.api_base_url).login()
    save_credentials(config.credentials_path, credentials)
    log.info("event=credentials_saved; path=%s", config.credentials_path)
    return credentials


def _direct_text(message: dict) -> str | None:
    if message.get("message_type") != 1 or message.get("group_id"):
        return None
    return inbound_text(message)


def _load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("cannot read enrollment environment file") from exc
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key.replace("_", "").isalnum() or not key[0].isalpha():
            raise RuntimeError("invalid enrollment environment file")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def enroll(env_file: Path | None = None) -> int:
    """Interactively identify one sender without forwarding enrollment traffic."""
    try:
        if env_file is not None:
            _load_env_file(env_file)
        config = Config.from_env(require_allowlist=False)
        config.data_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Enrollment setup failed: {exc.__class__.__name__}", file=sys.stderr)
        return 1

    if os.name == "posix" and os.stat(config.data_dir).st_mode & 0o077:
        print("Enrollment failed: data directory permissions must be 0700.", file=sys.stderr)
        return 1
    if Path("/run/systemd/system").is_dir():
        import subprocess

        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "wechat-muse-bridge.service"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            print("Enrollment failed: stop wechat-muse-bridge.service before enrolling.", file=sys.stderr)
            return 1

    try:
        credentials = obtain_credentials(config)
        state = BridgeState.load(config.state_path)
    except (OSError, RuntimeError, ILinkError) as exc:
        print(f"Enrollment setup failed: {exc.__class__.__name__}", file=sys.stderr)
        return 1

    challenge = secrets.token_urlsafe(9)
    print("Enrollment login is ready. Send this one-time code to the ClawBot from the intended WeChat account:")
    print(challenge)
    print("Waiting up to 5 minutes. No enrollment message will be sent to Muse.")

    ilink = ILinkClient(credentials, config.request_timeout_s)
    deadline = time.monotonic() + 300
    backoff = 1.0
    try:
        while time.monotonic() < deadline:
            try:
                batch = ilink.get_updates(state.cursor, config.poll_timeout_ms)
            except AuthExpired:
                print("Enrollment failed: iLink login expired; run enrollment again.", file=sys.stderr)
                return 1
            except ILinkError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, backoff))
                backoff = min(15.0, backoff * 2)
                continue

            backoff = 1.0
            matched_sender = next(
                (
                    message.get("from_user_id")
                    for message in batch.messages
                    if isinstance(message.get("from_user_id"), str)
                    and message.get("from_user_id")
                    and _direct_text(message) == challenge
                ),
                None,
            )
            if matched_sender:
                if not matched_sender.isprintable() or matched_sender != matched_sender.strip():
                    print("Enrollment failed: iLink returned an invalid sender ID.", file=sys.stderr)
                    return 1
                state.cursor = batch.cursor or state.cursor
                state.save(config.state_path)
                print(f"Enrolled from_user_id: {matched_sender}")
                print("Add this exact value to ALLOWED_USER_IDS, then enable the bridge service.")
                return 0
    except (OSError, RuntimeError) as exc:
        print(f"Enrollment failed: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    finally:
        ilink.close()

    print("Enrollment timed out after 5 minutes. Run the command again.", file=sys.stderr)
    return 1


def run(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "enroll":
        if len(args) == 1:
            return enroll()
        if len(args) == 3 and args[1] == "--env-file":
            return enroll(Path(args[2]))
        print("Usage: wechat-muse-bridge enroll [--env-file PATH]", file=sys.stderr)
        return 2
    if args:
        print("Usage: wechat-muse-bridge [enroll]", file=sys.stderr)
        return 2
    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        state = BridgeState.load(config.state_path)
        state.save(config.state_path)
        credentials = obtain_credentials(config)
        bridge = Bridge.create(config, state, credentials)
    except (OSError, RuntimeError, ILinkError) as exc:
        log.error("event=startup_failed; kind=%s", exc.__class__.__name__)
        return 1

    def stop(_signum, _frame):
        bridge.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("event=started; polling=true; muse_session=%s", state.muse_session_id)
    try:
        bridge.run()
    except AuthExpired:
        return 2
    finally:
        log.info("event=stopped")
    return 0


def main() -> None:
    raise SystemExit(run())
