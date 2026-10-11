from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.api.metrics import CURRENT_SQL, HISTORY_SQL, get_pinot, get_kafka
from app.config import Settings
from app.main import create_app
from app.services.pinot_client import PinotQueryError
from app.services.kafka_producer import KafkaPublishError

SNAPSHOT = dict(event_id="snapshot-1", event_timestamp=1791706865292,
                zone_id="ZONE_1", online_drivers=20, ride_requests=40,
                accepted_requests=25, cancelled_requests=5, waiting_drivers=8)


@pytest.fixture
def api():
    app = create_app(Settings(_env_file=None))
    pinot = AsyncMock()
    app.dependency_overrides[get_pinot] = lambda: pinot
    kafka = AsyncMock()
    app.dependency_overrides[get_kafka] = lambda: kafka
    with patch("app.main.MetricsKafkaProducer", return_value=kafka):
        with TestClient(app) as client:
            yield client, pinot
    kafka.start.assert_awaited_once()
    kafka.stop.assert_awaited_once()
    assert app.state.pinot._client.is_closed


def test_current_snapshot(api):
    client, pinot = api
    pinot.query.return_value = [SNAPSHOT]
    response = client.get("/api/metrics/current?zone_id=ZONE_1")
    assert response.status_code == 200
    assert response.json() == SNAPSHOT
    pinot.query.assert_awaited_once_with(CURRENT_SQL)


def test_empty_current_returns_zero_state(api):
    client, pinot = api
    pinot.query.return_value = []
    response = client.get("/api/metrics/current")
    assert response.status_code == 200
    assert response.json() == dict(zone_id="ZONE_1", event_id=None,
        event_timestamp=None, online_drivers=0, ride_requests=0,
        accepted_requests=0, cancelled_requests=0, waiting_drivers=0)


@pytest.mark.parametrize("empty", [False, True])
def test_history(api, empty):
    client, pinot = api
    point = {k: v for k, v in SNAPSHOT.items() if k not in ("event_id", "zone_id")}
    pinot.query.return_value = [] if empty else [point]
    response = client.get("/api/metrics/history?zone_id=ZONE_1&window=1h")
    assert response.status_code == 200
    assert response.json() == ([] if empty else [point])
    pinot.query.assert_awaited_once_with(HISTORY_SQL)
    assert "event_timestamp >= ago('PT1H')" in HISTORY_SQL
    assert "event_timestamp <= now()" in HISTORY_SQL
    assert "ORDER BY event_timestamp ASC" in HISTORY_SQL


@pytest.mark.parametrize("path", [
    "/api/metrics/current?zone_id=ZONE_2",
    "/api/metrics/current?zone_id=%27%20OR%201=1",
    "/api/metrics/history?zone_id=ZONE_2",
    "/api/metrics/history?window=24h",
])
def test_unsupported_parameters_rejected_without_query(api, path):
    client, pinot = api
    assert client.get(path).status_code == 422
    pinot.query.assert_not_awaited()


@pytest.mark.parametrize("path", ["current", "history"])
def test_pinot_failure_returns_service_unavailable(api, path):
    client, pinot = api
    pinot.query.side_effect = PinotQueryError("Internal query details")
    response = client.get(f"/api/metrics/{path}")
    assert response.status_code == 503
    assert response.json() == {"detail": "Analytics are temporarily unavailable. Please retry."}


@pytest.mark.parametrize("path", ["current", "history"])
def test_malformed_snapshot_is_not_an_empty_result(api, path):
    client, pinot = api
    pinot.query.return_value = [{"online_drivers": 20}]
    assert client.get(f"/api/metrics/{path}").status_code == 503


def test_health_does_not_require_pinot(api):
    client, pinot = api
    assert client.get("/health").json() == {"status": "ok"}
    pinot.query.assert_not_awaited()


def input_snapshot():
    return {k: v for k, v in SNAPSHOT.items() if k not in ("event_id", "event_timestamp")}


def test_valid_post_publishes_one_complete_event(api):
    from time import time_ns
    from uuid import UUID
    client, pinot = api
    kafka = client.app.dependency_overrides[get_kafka]()
    before = time_ns() // 1_000_000
    response = client.post("/api/metrics", json=input_snapshot())
    after = time_ns() // 1_000_000
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "accepted"
    assert UUID(accepted["event_id"]).version == 4
    assert before <= accepted["event_timestamp"] <= after
    kafka.publish.assert_awaited_once_with(dict(
        **input_snapshot(), event_id=accepted["event_id"],
        event_timestamp=accepted["event_timestamp"]))
    pinot.query.assert_not_awaited()


@pytest.mark.parametrize("changes", [
    {"online_drivers": -1}, {"online_drivers": 1.5},
    {"online_drivers": "20"}, {"online_drivers": True},
    {"online_drivers": None}, {"online_drivers": 2_147_483_648},
    {"accepted_requests": 40}, {"waiting_drivers": 21},
    {"zone_id": "ZONE_2"}, {"event_id": "client-generated"},
    {"event_timestamp": 1},
])
def test_invalid_post_does_not_publish(api, changes):
    client, pinot = api
    kafka = client.app.dependency_overrides[get_kafka]()
    response = client.post("/api/metrics", json=input_snapshot() | changes)
    assert response.status_code == 422
    kafka.publish.assert_not_awaited()
    pinot.query.assert_not_awaited()


@pytest.mark.parametrize("missing", list(input_snapshot()))
def test_incomplete_snapshot_rejected(api, missing):
    client, _ = api
    payload = input_snapshot()
    del payload[missing]
    assert client.post("/api/metrics", json=payload).status_code == 422
    client.app.dependency_overrides[get_kafka]().publish.assert_not_awaited()


def test_publish_failure_returns_503(api):
    client, _ = api
    kafka = client.app.dependency_overrides[get_kafka]()
    kafka.publish.side_effect = KafkaPublishError("private details")
    response = client.post("/api/metrics", json=input_snapshot())
    assert response.status_code == 503
    assert response.json() == {"detail": "Unable to publish metrics event to Kafka."}
    kafka.publish.assert_awaited_once()


def test_dashboard_queries_concurrently_and_returns_combined_data(api):
    import asyncio
    client, pinot = api
    point = {k: v for k, v in SNAPSHOT.items() if k not in ("event_id", "zone_id")}
    started = set()
    both_started = asyncio.Event()

    async def query(sql):
        started.add(sql)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return [SNAPSHOT] if sql == CURRENT_SQL else [point]

    pinot.query.side_effect = query
    response = client.get("/api/dashboard?zone_id=ZONE_1&window=1h")
    assert response.status_code == 200
    assert response.json() == {"current": SNAPSHOT, "history": [point]}
    assert started == {CURRENT_SQL, HISTORY_SQL}
    assert pinot.query.await_count == 2


def test_empty_dashboard_returns_zero_state_and_empty_history(api):
    client, pinot = api
    pinot.query.return_value = []
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["current"]["event_timestamp"] is None
    assert response.json()["current"]["online_drivers"] == 0
    assert response.json()["history"] == []


def test_dashboard_can_return_current_snapshot_without_recent_history(api):
    client, pinot = api
    async def query(sql):
        return [SNAPSHOT] if sql == CURRENT_SQL else []
    pinot.query.side_effect = query
    assert client.get("/api/dashboard").json() == {"current": SNAPSHOT, "history": []}


@pytest.mark.parametrize("failed_sql", [CURRENT_SQL, HISTORY_SQL])
def test_dashboard_query_failure_returns_503(api, failed_sql):
    client, pinot = api
    async def query(sql):
        if sql == failed_sql:
            raise PinotQueryError("Unavailable")
        return []
    pinot.query.side_effect = query
    assert client.get("/api/dashboard").status_code == 503


@pytest.mark.parametrize("query", ["zone_id=ZONE_2", "window=24h"])
def test_dashboard_rejects_unsupported_parameters(api, query):
    client, pinot = api
    assert client.get(f"/api/dashboard?{query}").status_code == 422
    pinot.query.assert_not_awaited()


@pytest.mark.parametrize("malformed_sql", [CURRENT_SQL, HISTORY_SQL])
def test_dashboard_invalid_results_are_not_zero_state(api, malformed_sql):
    client, pinot = api
    async def query(sql):
        return [{"online_drivers": 1}] if sql == malformed_sql else []
    pinot.query.side_effect = query
    assert client.get("/api/dashboard").status_code == 503


@pytest.mark.parametrize("missing", ["zone_id", "event_id", "event_timestamp"])
def test_stored_metadata_must_not_be_filled_with_defaults(api, missing):
    client, pinot = api
    row = dict(SNAPSHOT)
    del row[missing]
    pinot.query.return_value = [row]
    assert client.get("/api/metrics/current").status_code == 503
