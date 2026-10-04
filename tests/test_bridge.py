import logging

import pytest

from wechat_muse_bridge.bridge import Bridge
from wechat_muse_bridge.config import Config
from wechat_muse_bridge.ilink.models import AuthExpired, UpdateBatch
from wechat_muse_bridge.muse.client import MuseError
from wechat_muse_bridge.state import BridgeState


class FakeILink:
    def __init__(self, batch=None, error=None):
        self.batch = batch
        self.error = error
        self.calls = []
        self.closed = False

    def get_updates(self, cursor, timeout):
        self.calls.append((cursor, timeout))
        if self.error:
            raise self.error
        return self.batch

    def close(self):
        self.closed = True


class FakeMuse:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def send_user_message(self, session, text):
        self.calls.append((session, text))
        if self.error:
            raise self.error
        return 1.0


def make_bridge(tmp_path, ilink=None, muse=None):
    config = Config(tmp_path, frozenset({"allowed-user"}), ("musegadget",))
    state = BridgeState(cursor="old-cursor", muse_session_id="session-1")
    state.save(config.state_path)
    ilink = ilink or FakeILink(UpdateBatch((), "new-cursor", 0))
    muse = muse or FakeMuse()
    return Bridge(config, state, ilink, muse), ilink, muse


def msg(message_id="m1", sender="allowed-user", text="hello", **extra):
    return {
        "message_id": message_id,
        "from_user_id": sender,
        "message_type": 1,
        "group_id": "",
        "item_list": [{"type": 1, "text_item": {"text": text}}],
        **extra,
    }


def test_allowed_message_envelope_and_state_persisted(tmp_path):
    bridge, _, muse = make_bridge(tmp_path)
    bridge.process_batch((msg(text="hello Muse"),), "new-cursor")
    assert muse.calls == [("session-1", "[via WeChat]\n\nhello Muse")]
    assert bridge.state.cursor == "new-cursor"
    assert bridge.state.last_message_id == "m1"


def test_unauthorized_message_never_reaches_muse_and_cursor_commits(tmp_path, caplog):
    bridge, _, muse = make_bridge(tmp_path)
    with caplog.at_level(logging.INFO):
        bridge.process_batch((msg(sender="intruder", text="secret text"),), "c2")
    assert muse.calls == []
    assert bridge.state.cursor == "c2"
    assert "intruder" not in caplog.text
    assert "secret text" not in caplog.text


def test_reset_rotates_uuid_without_sending_message(tmp_path):
    bridge, _, muse = make_bridge(tmp_path)
    before = bridge.state.muse_session_id
    bridge.process_batch((msg(text="/reset"),), "c2")
    assert bridge.state.muse_session_id != before
    assert muse.calls == []


def test_group_nontext_and_over_limit_are_not_delivered(tmp_path):
    bridge, _, muse = make_bridge(tmp_path)
    bridge.config = Config(tmp_path, frozenset({"allowed-user"}), ("musegadget",), max_message_chars=5)
    bridge.process_batch((msg("group", group_id="g1"), msg("long", text="123456")), "c2")
    assert muse.calls == []
    assert bridge.state.cursor == "c2"


def test_muse_failure_does_not_advance_cursor_or_last_id(tmp_path):
    bridge, _, _ = make_bridge(tmp_path, muse=FakeMuse(MuseError("offline")))
    with pytest.raises(MuseError):
        bridge.process_batch((msg(),), "new-cursor")
    assert bridge.state.cursor == "old-cursor"
    assert bridge.state.last_message_id == ""
    assert BridgeState.load(tmp_path / "state.json").cursor == "old-cursor"


def test_cursor_not_committed_when_later_message_in_batch_fails(tmp_path):
    muse = FakeMuse()
    bridge, _, _ = make_bridge(tmp_path, muse=muse)
    class FailSecondMuse(FakeMuse):
        def send_user_message(self, session, text):
            if "second" in text:
                raise MuseError("offline")
            return super().send_user_message(session, text)
    bridge.muse = FailSecondMuse()
    with pytest.raises(MuseError):
        bridge.process_batch((msg("m1", text="first"), msg("m2", text="second")), "new-cursor")
    assert bridge.state.cursor == "old-cursor"
    assert bridge.state.pending_message_ids == ["m1"]
    # The successful first delivery is remembered so an in-process replay won't redeliver it.
    bridge.muse = muse
    bridge.process_batch((msg("m1", text="first"),), "replayed-cursor")
    assert muse.calls == []
    assert bridge.state.cursor == "replayed-cursor"


def test_duplicate_message_id_is_not_repeated(tmp_path):
    bridge, _, muse = make_bridge(tmp_path)
    bridge.process_batch((msg(),), "c1")
    bridge.process_batch((msg(),), "c2")
    assert len(muse.calls) == 1


def test_pending_message_ids_restore_deduplication_after_restart(tmp_path):
    state = BridgeState(
        cursor="old-cursor",
        muse_session_id="session-1",
        last_message_id="m0",
        pending_message_ids=["m1", "m2"],
    )
    state.save(tmp_path / "state.json")
    restored = BridgeState.load(tmp_path / "state.json")
    muse = FakeMuse()
    bridge = Bridge(
        Config(tmp_path, frozenset({"allowed-user"}), ("musegadget",)),
        restored,
        FakeILink(UpdateBatch((), "new-cursor", 0)),
        muse,
    )

    bridge.process_batch((msg("m1"), msg("m2")), "new-cursor")

    assert muse.calls == []
    assert bridge.state.cursor == "new-cursor"


def test_run_dispatches_batch_and_commits_cursor(tmp_path):
    bridge, ilink, _ = make_bridge(
        tmp_path, ilink=FakeILink(UpdateBatch((msg(),), "run-cursor", 0))
    )

    class StopAfterDelivery(FakeMuse):
        def send_user_message(self, session, text):
            result = super().send_user_message(session, text)
            bridge.stop()
            return result

    muse = StopAfterDelivery()
    bridge.muse = muse
    bridge.run()

    assert muse.calls == [("session-1", "[via WeChat]\n\nhello")]
    assert bridge.state.cursor == "run-cursor"
    assert BridgeState.load(tmp_path / "state.json").cursor == "run-cursor"
    assert ilink.closed


def test_auth_expiration_pauses_polling_until_shutdown(tmp_path, monkeypatch):
    bridge, ilink, _ = make_bridge(tmp_path, ilink=FakeILink(error=AuthExpired("expired")))
    sleeps = []
    def stop_after_wait(_):
        sleeps.append(1)
        bridge.stop()
    monkeypatch.setattr("wechat_muse_bridge.bridge.time.sleep", stop_after_wait)
    bridge.run()
    assert ilink.closed
    assert sleeps == [1]
    assert ilink.calls[0][0] == "old-cursor"
