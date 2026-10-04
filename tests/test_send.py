import io
from pathlib import Path

import pytest

import wechat_muse_bridge.send as send_mod
from wechat_muse_bridge.send import chunk_text, clean_text, main


def test_clean_text_strips_widget_tokens_and_collapses_blank_lines():
    text = "hello [[hatch_widget:widget-1234]] world\n\n\n\nnext"
    assert clean_text(text) == "hello  world\n\nnext"


def test_clean_text_strips_surrounding_whitespace():
    assert clean_text("  hi\n") == "hi"
    assert clean_text("") == ""


def test_chunk_text_short_text_is_single_chunk():
    assert chunk_text("hello") == ["hello"]


def test_chunk_text_splits_on_paragraph_boundaries():
    paras = ["p1", "p2", "p3"]
    text = "\n\n".join(paras)
    assert chunk_text(text, limit=5) == paras


def test_chunk_text_packs_paragraphs_until_limit():
    assert chunk_text("p1\n\np2", limit=10) == ["p1\n\np2"]


def test_chunk_text_hard_splits_oversized_paragraph():
    text = "x" * 25
    assert chunk_text(text, limit=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_chunk_text_empty_gives_single_empty_chunk():
    assert chunk_text("") == [""]


class FakeConfig:
    max_message_chars = 8000
    log_level = "CRITICAL"
    request_timeout_s = 1.0

    def __init__(self, tmp_path):
        self.state_path = tmp_path / "state.json"
        self.credentials_path = tmp_path / "credentials.json"

    @classmethod
    def from_env(cls, require_allowlist=False):
        return cls._instance


class FakeState:
    reply_to_user_id = "user-1"
    reply_context_token = "ctx-1"


class FakeILinkClient:
    instances = []

    def __init__(self, credentials, timeout_s):
        self.sent = []
        FakeILinkClient.instances.append(self)

    def send_message(self, to_user_id, context_token, text):
        self.sent.append((to_user_id, context_token, text))

    def close(self):
        pass


@pytest.fixture
def send_env(tmp_path, monkeypatch):
    FakeConfig._instance = FakeConfig(tmp_path)
    FakeILinkClient.instances.clear()
    monkeypatch.setattr(send_mod, "Config", FakeConfig)
    monkeypatch.setattr(send_mod, "BridgeState", type("S", (), {"load": staticmethod(lambda p: FakeState())}))
    monkeypatch.setattr(send_mod, "ILinkClient", FakeILinkClient)
    monkeypatch.setattr(send_mod, "load_credentials", lambda p: object())
    return tmp_path


def test_main_sends_text_args_to_captured_recipient(send_env, capsys):
    # NOTE: matches Pi v0.2.0 behavior — argv parts are concatenated as-is.
    assert main(["hello", "world"]) == 0
    sent = FakeILinkClient.instances[0].sent
    assert sent == [("user-1", "ctx-1", "helloworld")]


def test_main_explicit_recipient_overrides_state(send_env):
    assert main(["--to-user-id", "u9", "--context-token", "c9", "hi"]) == 0
    sent = FakeILinkClient.instances[0].sent
    assert sent[0][0] == "u9"
    assert sent[0][1] == "c9"


def test_main_unknown_option_is_usage_error(send_env, capsys):
    assert main(["--bogus"]) == 2


def test_main_empty_text_fails(send_env, capsys):
    assert main(["   "]) == 1


def test_main_no_recipient_captured_fails(send_env, monkeypatch):
    class NoRecipient:
        reply_to_user_id = ""
        reply_context_token = ""
    monkeypatch.setattr(send_mod, "BridgeState", type("S", (), {"load": staticmethod(lambda p: NoRecipient())}))
    assert main(["hello"]) == 1
    assert FakeILinkClient.instances == []


def test_main_reads_stdin_with_dash(send_env, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    assert main(["-"]) == 0
    sent = FakeILinkClient.instances[0].sent
    assert sent == [("user-1", "ctx-1", "from stdin")]
