import subprocess

import pytest

from wechat_muse_bridge.muse.client import MuseClient, MuseError


def test_muse_cli_uses_argv_and_stdin_without_shell():
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="Sent", stderr="")
    client = MuseClient(("/usr/local/bin/musegadget",), runner=runner)
    client.send_user_message("session-123", "a message; $(danger)")
    args, kwargs = calls[0]
    assert args == ["/usr/local/bin/musegadget", "send-user-msg", "--session-id", "session-123", "-"]
    assert kwargs["input"] == "a message; $(danger)"
    assert "shell" not in kwargs
    assert kwargs["capture_output"] is True


def test_muse_cli_nonzero_does_not_leak_output():
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="secret body", stderr="secret token")
    client = MuseClient(("musegadget",), runner=runner)
    with pytest.raises(MuseError, match="status 1") as exc:
        client.send_user_message("s", "secret body")
    assert "secret" not in str(exc.value)


def test_muse_cli_timeout_is_a_delivery_error():
    def runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    client = MuseClient(("musegadget",), runner=runner)
    with pytest.raises(MuseError, match="timed out"):
        client.send_user_message("s", "hello")
