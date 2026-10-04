import json
import os
import re

from wechat_muse_bridge.state import BridgeState


def test_missing_state_gets_valid_uuid_and_roundtrips(tmp_path):
    path = tmp_path / "state.json"
    state = BridgeState.load(path)
    assert re.fullmatch(r"[0-9a-f-]{36}", state.muse_session_id)
    state.cursor = "opaque-cursor"
    state.last_message_id = "msg-1"
    state.save(path)
    loaded = BridgeState.load(path)
    assert loaded == state
    assert json.loads(path.read_text())["cursor"] == "opaque-cursor"


def test_state_saved_private_and_reset_rotates_session(tmp_path):
    path = tmp_path / "state.json"
    state = BridgeState.load(path)
    before = state.muse_session_id
    state.save(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    state.reset_session()
    assert state.muse_session_id != before
    assert re.fullmatch(r"[A-Za-z0-9-]{1,64}", state.muse_session_id)


def test_invalid_persisted_session_is_replaced(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"muse_session_id":"bad session","cursor":"x"}')
    state = BridgeState.load(path)
    assert state.cursor == "x"
    assert re.fullmatch(r"[0-9a-f-]{36}", state.muse_session_id)
