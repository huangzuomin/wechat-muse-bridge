import httpx
import pytest

from wechat_muse_bridge.ilink.client import ILinkClient
from wechat_muse_bridge.ilink.models import AuthExpired, Credentials, ProtocolError


def make_client(handler):
    client = ILinkClient(Credentials("token", "bot", "https://api.example"))
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_get_updates_posts_cursor_and_parses_batch():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"ret": 0, "msgs": [{"message_id": "m1"}], "get_updates_buf": "c2"})
    client = make_client(handler)
    batch = client.get_updates("c1", 35000)
    assert batch.cursor == "c2"
    assert batch.messages[0]["message_id"] == "m1"
    assert seen["url"] == "https://api.example/ilink/bot/getupdates"
    assert seen["json"]["get_updates_buf"] == "c1"
    assert seen["json"]["longpolling_timeout_ms"] == 35000
    assert seen["headers"]["authorization"] == "Bearer token"
    client.close()


@pytest.mark.parametrize("body", [{"ret": -14}, {"ret": 0, "errcode": -14}])
def test_minus_14_is_auth_expired(body):
    client = make_client(lambda request: httpx.Response(200, json=body))
    with pytest.raises(AuthExpired):
        client.get_updates("", 35000)
    client.close()


def test_nonzero_errcode_is_protocol_error():
    body = {"ret": 0, "errcode": 1, "msgs": [{"message_id": "m1"}], "get_updates_buf": "c2"}
    client = make_client(lambda request: httpx.Response(200, json=body))
    with pytest.raises(ProtocolError, match="errcode=1"):
        client.get_updates("c1", 35000)
    client.close()


def test_invalid_payload_is_protocol_error():
    client = make_client(lambda request: httpx.Response(200, json={"ret": 0, "msgs": {}, "get_updates_buf": ""}))
    with pytest.raises(ProtocolError):
        client.get_updates("", 35000)
    client.close()
