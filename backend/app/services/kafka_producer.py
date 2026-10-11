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


class OperationsKafkaProducer:
    """Per-run ordered publisher. Never retries a failed batch at application level."""

    def __init__(self, bootstrap_servers: str, timeout: float = 10.0):
        self._bootstrap_servers = bootstrap_servers
        self._timeout = timeout
        self._producer: AIOKafkaProducer | None = None
        self.acknowledged_events = 0

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode('utf-8'),
            acks='all', enable_idempotence=True, linger_ms=5,
            request_timeout_ms=int(self._timeout * 1000),
        )
        try:
            await asyncio.wait_for(self._producer.start(), timeout=self._timeout)
        except (KafkaError, TimeoutError) as exc:
            raise KafkaPublishError('Unable to start operations producer') from exc

    def _delivery_done(self, future) -> None:
        # Observe exceptions even if enqueueing a later record fails.
        if not future.cancelled() and future.exception() is None:
            self.acknowledged_events += 1

    async def publish_batch(self, events) -> None:
        if self._producer is None:
            raise KafkaPublishError('Operations producer is not started')
        try:
            async with asyncio.timeout(self._timeout):
                deliveries = []
                for event in events:
                    delivery = await self._producer.send(
                        'ride-operations', value=event.to_dict(), partition=0)
                    delivery.add_done_callback(self._delivery_done)
                    deliveries.append(delivery)
                if deliveries:
                    # A timeout cannot undo Kafka sends. Keep delivery futures alive
                    # so stop() can drain them, and do not replay this batch.
                    results = await asyncio.gather(
                        *(asyncio.shield(delivery) for delivery in deliveries),
                        return_exceptions=True)
                    failure = next((result for result in results if isinstance(result, BaseException)), None)
                    if failure is not None:
                        raise KafkaPublishError('Operations batch delivery failed') from failure
        except (KafkaError, TimeoutError) as exc:
            raise KafkaPublishError('Unable to confirm operations batch delivery') from exc

    async def stop(self) -> None:
        if self._producer is not None:
            try:
                # aiokafka stop drains queued sends; bound cleanup during outages.
                await asyncio.wait_for(self._producer.stop(), timeout=self._timeout)
            except (KafkaError, TimeoutError) as exc:
                raise KafkaPublishError('Unable to drain operations producer') from exc
            finally:
                self._producer = None
