import asyncio
import json

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError


class KafkaPublishError(RuntimeError):
    """The producer could not confirm publication."""


class MetricsKafkaProducer:
    def __init__(self, bootstrap_servers: str, topic: str, timeout: float = 10.0):
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._timeout = timeout
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            acks="all",
            enable_idempotence=True,
            request_timeout_ms=int(self._timeout * 1000),
        )
        await asyncio.wait_for(self._producer.start(), timeout=self._timeout)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, event: dict) -> None:
        if self._producer is None:
            raise KafkaPublishError("Kafka producer is not started")
        try:
            await asyncio.wait_for(
                self._producer.send_and_wait(self._topic, value=event),
                timeout=self._timeout,
            )
        except (KafkaError, TimeoutError) as exc:
            raise KafkaPublishError("Unable to confirm publication to Kafka") from exc
