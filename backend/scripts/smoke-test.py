"""Verify POST -> Kafka -> Pinot using the running API; adds one snapshot."""
import asyncio
import json
import time
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition
import httpx

from app.config import Settings


async def main():
    settings = Settings()
    payload = dict(zone_id="ZONE_1", online_drivers=75, ride_requests=100,
                   accepted_requests=60, cancelled_requests=15, waiting_drivers=20)
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        enable_auto_commit=False, group_id=None,
    )
    await consumer.start()
    try:
        partition = TopicPartition(settings.kafka_topic, 0)
        consumer.assign([partition])
        await consumer.seek_to_end(partition)
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=20) as api:
            for changes in ({"waiting_drivers": 76}, {"accepted_requests": 100}):
                response = await api.post("/api/metrics", json=payload | changes)
                assert response.status_code == 422, response.text
            assert not await consumer.getmany(timeout_ms=500), "Invalid input produced an event"
            response = await api.post("/api/metrics", json=payload)
            assert response.status_code == 202, response.text
            accepted = response.json()
            assert UUID(accepted["event_id"]).version == 4
            message = await asyncio.wait_for(consumer.getone(), timeout=20)
            event = json.loads(message.value)
            expected = payload | {"event_id": accepted["event_id"],
                                  "event_timestamp": accepted["event_timestamp"]}
            assert event == expected, event
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                current = await api.get("/api/metrics/current")
                history = await api.get("/api/metrics/history")
                if current.status_code == 200 and history.status_code == 200:
                    if current.json() == expected:
                        matches = [row for row in history.json()
                                   if row["event_timestamp"] == expected["event_timestamp"]]
                        point = {k: v for k, v in expected.items() if k not in ("zone_id", "event_id")}
                        if matches == [point]:
                            break
                await asyncio.sleep(2)
            else:
                raise AssertionError("Snapshot did not appear in current metrics and history")
            async with httpx.AsyncClient(timeout=10) as broker:
                result = await broker.post(
                    str(settings.pinot_broker_url).rstrip("/") + "/query/sql",
                    json={"sql": "SELECT COUNT(*) FROM ride_metrics WHERE event_id = "
                          f"'{accepted['event_id']}'"},
                )
                result.raise_for_status()
                result = result.json()
                assert not result.get("exceptions"), result
                assert result["resultTable"]["rows"] == [[1]], result
            print("PASS: invalid submissions emitted nothing; valid POST produced one complete")
            print("Kafka event, one Pinot row, and matching current/history responses.")
            print(json.dumps(expected, indent=2))
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
