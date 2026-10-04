import base64

from wechat_muse_bridge.ilink.protocol import common_headers, get_updates_body, inbound_text


def test_headers_use_documented_auth_and_decimal_client_version():
    headers = common_headers(authenticated=True, bot_token="secret-token")
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["AuthorizationType"] == "ilink_bot_token"
    assert headers["iLink-App-ClientVersion"] == str(int("0x00020408", 16))
    assert base64.b64decode(headers["X-WECHAT-UIN"]).decode().isdigit()


def test_qr_headers_omit_auth():
    headers = common_headers(authenticated=False)
    assert "Authorization" not in headers
    assert "AuthorizationType" not in headers


def test_get_updates_sends_cursor_timeout_and_base_info():
    body = get_updates_body("cursor-1", 35000)
    assert body["get_updates_buf"] == "cursor-1"
    assert body["longpolling_timeout_ms"] == 35000
    assert body["base_info"]["channel_version"] == "2.4.8"


def test_extracts_only_direct_text_items():
    message = {
        "message_type": 1,
        "group_id": "",
        "item_list": [
            {"type": 1, "text_item": {"text": "hello "}},
            {"type": 3, "voice_item": {"text": "ignored"}},
            {"type": 1, "text_item": {"text": "world"}},
        ],
    }
    assert inbound_text(message) == "hello world"
    assert inbound_text({**message, "group_id": "group-x"}) is None
    assert inbound_text({**message, "message_type": 2}) is None
