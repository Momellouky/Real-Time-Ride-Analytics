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
