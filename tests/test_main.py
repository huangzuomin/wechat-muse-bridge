import json

import pytest

from wechat_muse_bridge.ilink.models import Credentials, ProtocolError
from wechat_muse_bridge.main import load_credentials, save_credentials
from wechat_muse_bridge.state import BridgeState


def test_credentials_atomic_save_roundtrip_and_private_mode(tmp_path):
    path = tmp_path / "credentials.json"
    credentials = Credentials("top-secret", "bot-id", "https://ilink.example", "user-id")
    save_credentials(path, credentials)
    assert load_credentials(path) == credentials
    if path.stat().st_mode & 0o777 != 0o600 and __import__("os").name != "nt":
        pytest.fail("credentials file permissions are not 0600")
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_credentials_requests_login(tmp_path):
    assert load_credentials(tmp_path / "credentials.json") is None


def test_credentials_reject_non_https_base_url(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"bot_token": "t", "bot_id": "b", "base_url": "http://bad"}))
    with pytest.raises(ProtocolError):
        load_credentials(path)


def test_enroll_routes_before_allowlist_validation_and_never_builds_muse(tmp_path, monkeypatch, capsys):
    from wechat_muse_bridge import main
    from wechat_muse_bridge.config import Config
    from wechat_muse_bridge.ilink.models import UpdateBatch

    config = Config(tmp_path, frozenset(), ("musegadget",))
    monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls, **kwargs: config))
    monkeypatch.setattr(main, "obtain_credentials", lambda _config: Credentials("private-token", "bot", "https://api.example"))
    monkeypatch.setattr(main, "MuseClient", lambda *_: pytest.fail("enrollment must not create MuseClient"))
    monkeypatch.setattr(main, "Bridge", type("NoBridge", (), {"create": staticmethod(lambda *_: pytest.fail("enrollment must not create Bridge"))}))
    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda _size: "enroll-code")

    class FakeILink:
        def __init__(self, *_args):
            self.calls = []
        def get_updates(self, cursor, timeout):
            self.calls.append((cursor, timeout))
            return UpdateBatch(({
                "message_id": "enroll-1",
                "from_user_id": "exact-sender-id",
                "message_type": 1,
                "group_id": "",
                "item_list": [{"type": 1, "text_item": {"text": "enroll-code"}}],
            },), "cursor-after-enrollment", 0)
        def close(self):
            pass

    monkeypatch.setattr(main, "ILinkClient", FakeILink)
    assert main.run(["enroll"]) == 0
    output = capsys.readouterr().out
    assert "exact-sender-id" in output
    assert "private-token" not in output
    assert BridgeState.load(config.state_path).cursor == "cursor-after-enrollment"


def test_enroll_loads_explicit_environment_file(tmp_path, monkeypatch, capsys):
    from wechat_muse_bridge import main
    from wechat_muse_bridge.config import Config
    from wechat_muse_bridge.ilink.models import UpdateBatch

    env_file = tmp_path / "env"
    env_file.write_text("WECHAT_MUSE_DATA_DIR=/custom/data\nILINK_API_BASE_URL=https://ilink.example\n")
    config = Config(tmp_path / "custom-data", frozenset(), ("musegadget",), api_base_url="https://ilink.example")
    monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls, **kwargs: config))
    monkeypatch.setattr(main, "obtain_credentials", lambda _config: Credentials("token", "bot", "https://api.example"))
    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda _size: "enroll-code")

    class FakeILink:
        def __init__(self, credentials, *_args):
            assert credentials.bot_token == "token"
        def get_updates(self, cursor, timeout):
            return UpdateBatch(({
                "from_user_id": "sender-id",
                "message_type": 1,
                "group_id": "",
                "item_list": [{"type": 1, "text_item": {"text": "enroll-code"}}],
            },), "cursor", 0)
        def close(self):
            pass

    monkeypatch.setattr(main, "ILinkClient", FakeILink)
    assert main.run(["enroll", "--env-file", str(env_file)]) == 0
    assert "sender-id" in capsys.readouterr().out


def test_enroll_ignores_nonmatching_messages_and_times_out_without_committing_cursor(tmp_path, monkeypatch, capsys):
    from wechat_muse_bridge import main
    from wechat_muse_bridge.config import Config
    from wechat_muse_bridge.ilink.models import UpdateBatch
    from wechat_muse_bridge.state import BridgeState

    config = Config(tmp_path, frozenset(), ("musegadget",))
    monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls, **kwargs: config))
    monkeypatch.setattr(main, "obtain_credentials", lambda _config: Credentials("token", "bot", "https://api.example"))
    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda _size: "enroll-code")
    monkeypatch.setattr(main.time, "monotonic", iter([0.0, 301.0]).__next__)

    class FakeILink:
        def __init__(self, *_args):
            self.calls = []
        def get_updates(self, cursor, timeout):
            self.calls.append((cursor, timeout))
            return UpdateBatch(({
                "message_id": "other-1",
                "from_user_id": "other-sender",
                "message_type": 1,
                "group_id": "",
                "item_list": [{"type": 1, "text_item": {"text": "private message"}}],
            },), "uncommitted-cursor", 0)
        def close(self):
            pass

    monkeypatch.setattr(main, "ILinkClient", FakeILink)
    assert main.run(["enroll"]) == 1
    output = capsys.readouterr()
    assert "private message" not in output.out
    assert "other-sender" not in output.out
    assert "private message" not in output.err
    assert not config.state_path.exists()


def test_production_run_still_fails_closed_without_allowlist(monkeypatch, capsys):
    from wechat_muse_bridge import main

    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    assert main.run([]) == 2
    assert "ALLOWED_USER_IDS" in capsys.readouterr().err


def test_qr_status_rejects_non_object_response():
    import httpx

    from wechat_muse_bridge.ilink.auth import ILinkAuth

    class FakeClient:
        def get(self, url, **_kwargs):
            return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    auth = ILinkAuth(FakeClient(), "https://api.example")
    with pytest.raises(ProtocolError, match="QR status response must be an object"):
        auth._wait_for_confirmation("qr-token")


def test_enroll_refuses_when_systemd_service_is_active(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    from wechat_muse_bridge import main
    from wechat_muse_bridge.config import Config

    config = Config(tmp_path / "data", frozenset(), ("musegadget",))
    monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls, **kwargs: config))
    monkeypatch.setattr(Path, "is_dir", lambda self: str(self).replace("\\", "/") == "/run/systemd/system")

    class ActiveService:
        returncode = 0

    def run(*_args, **_kwargs):
        return ActiveService()

    import subprocess

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        main,
        "obtain_credentials",
        lambda _config: pytest.fail("active service must be checked before iLink login"),
    )

    assert main.run(["enroll"]) == 1
    assert "stop wechat-muse-bridge.service" in capsys.readouterr().err


def test_enroll_rejects_group_message_even_if_code_matches(tmp_path, monkeypatch, capsys):

    from wechat_muse_bridge import main
    from wechat_muse_bridge.config import Config
    from wechat_muse_bridge.ilink.models import UpdateBatch

    config = Config(tmp_path, frozenset(), ("musegadget",))
    monkeypatch.setattr(main.Config, "from_env", classmethod(lambda cls, **kwargs: config))
    monkeypatch.setattr(main, "obtain_credentials", lambda _config: Credentials("token", "bot", "https://api.example"))
    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda _size: "enroll-code")
    monkeypatch.setattr(main.time, "monotonic", iter([0.0, 301.0]).__next__)

    class FakeILink:
        def __init__(self, *_args):
            pass
        def get_updates(self, cursor, timeout):
            return UpdateBatch(({
                "from_user_id": "group-sender",
                "message_type": 1,
                "group_id": "group-1",
                "item_list": [{"type": 1, "text_item": {"text": "enroll-code"}}],
            },), "group-cursor", 0)
        def close(self):
            pass

    monkeypatch.setattr(main, "ILinkClient", FakeILink)
    assert main.run(["enroll"]) == 1
    output = capsys.readouterr()
    assert "group-sender" not in output.out
    assert not config.state_path.exists()


@pytest.mark.parametrize(
    "url",
    ["http://ilink.example", "ftp://ilink.example", "//ilink.example", "https:///missing-host"],
)
def test_config_rejects_non_https_api_base_url(monkeypatch, url):
    from wechat_muse_bridge.config import Config

    monkeypatch.setenv("ILINK_API_BASE_URL", url)
    with pytest.raises(ValueError, match="ILINK_API_BASE_URL must be an HTTPS URL with a hostname"):
        Config.from_env(require_allowlist=False)


def test_config_accepts_https_api_base_url_and_strips_trailing_slash(monkeypatch):
    from wechat_muse_bridge.config import Config

    monkeypatch.setenv("ILINK_API_BASE_URL", "https://ilink.example/")
    assert Config.from_env(require_allowlist=False).api_base_url == "https://ilink.example"
