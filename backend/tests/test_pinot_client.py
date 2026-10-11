import httpx
import pytest

from app.services.pinot_client import PinotClient, PinotQueryError


def result(rows):
    return {"resultTable": {"dataSchema": {"columnNames": ["event_id", "online_drivers"]},
                            "rows": rows}, "exceptions": []}


@pytest.mark.parametrize("rows, expected", [
    ([["a", 20], ["b", 30]], [{"event_id": "a", "online_drivers": 20},
                              {"event_id": "b", "online_drivers": 30}]),
    ([], []),
])
async def test_response_mapping(rows, expected):
    def handler(request):
        assert request.url.path == "/query/sql"
        assert request.content == b'{"sql":"SELECT test"}'
        return httpx.Response(200, json=result(rows))
    client = PinotClient("http://broker/", transport=httpx.MockTransport(handler))
    try:
        assert await client.query("SELECT test") == expected
    finally:
        await client.close()
    assert client._client.is_closed


@pytest.mark.parametrize("payload", [
    {"exceptions": [{"errorCode": 150, "message": "SQL error"}]},
    {**result([]), "partialResult": True},
    {**result([]), "numServersQueried": 2, "numServersResponded": 1},
    {}, result([["a"]]), result([["a", 20, 30]]),
    {"resultTable": None}, [],
])
async def test_invalid_or_incomplete_result_raises(payload):
    client = PinotClient("http://broker", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(PinotQueryError):
            await client.query("SELECT test")
    finally:
        await client.close()


@pytest.mark.parametrize("failure", ["http", "timeout", "json"])
async def test_transport_and_decode_errors(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        if failure == "http":
            return httpx.Response(503)
        return httpx.Response(200, text="not JSON")
    client = PinotClient("http://broker", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PinotQueryError):
            await client.query("SELECT test")
    finally:
        await client.close()
