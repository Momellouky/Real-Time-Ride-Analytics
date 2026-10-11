import asyncio
import json
from unittest.mock import AsyncMock, patch

from aiokafka.errors import KafkaConnectionError
import pytest

from app.services.kafka_producer import MetricsKafkaProducer, KafkaPublishError


async def test_acknowledged_publish_and_cleanup():
    underlying = AsyncMock()
    producer = MetricsKafkaProducer("kafka:9092", "snapshots")
    with patch("app.services.kafka_producer.AIOKafkaProducer", return_value=underlying) as factory:
        await producer.start()
        options = factory.call_args.kwargs
        assert options["acks"] == "all"
        assert options["enable_idempotence"] is True
        assert json.loads(options["value_serializer"]({"online_drivers": 20})) == {"online_drivers": 20}
        await producer.publish({"event_id": "test"})
        underlying.send_and_wait.assert_awaited_once_with("snapshots", value={"event_id": "test"})
        await producer.stop()
        underlying.stop.assert_awaited_once()
        assert producer._producer is None


async def test_unstarted_producer_rejects_publish():
    with pytest.raises(KafkaPublishError):
        await MetricsKafkaProducer("kafka:9092", "snapshots").publish({})


@pytest.mark.parametrize("timeout", [False, True])
async def test_failed_publish_is_not_acknowledged(timeout):
    underlying = AsyncMock()
    if timeout:
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        underlying.send_and_wait.side_effect = slow
    else:
        underlying.send_and_wait.side_effect = KafkaConnectionError("offline")
    producer = MetricsKafkaProducer("kafka:9092", "snapshots", timeout=0.01)
    with patch("app.services.kafka_producer.AIOKafkaProducer", return_value=underlying):
        await producer.start()
        try:
            with pytest.raises(KafkaPublishError):
                await producer.publish({})
        finally:
            await producer.stop()


def test_startup_failure_closes_both_clients():
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    kafka, pinot = AsyncMock(), AsyncMock()
    kafka.start.side_effect = KafkaConnectionError("offline")
    app = create_app(Settings(_env_file=None))
    with patch("app.main.MetricsKafkaProducer", return_value=kafka), patch("app.main.PinotClient", return_value=pinot):
        with pytest.raises(KafkaConnectionError):
            with TestClient(app):
                pass
    kafka.stop.assert_awaited_once()
    pinot.close.assert_awaited_once()
