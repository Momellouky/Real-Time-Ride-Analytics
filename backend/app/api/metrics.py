import asyncio
from typing import Annotated, Literal
from time import time_ns
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.models.metrics import (
    CurrentMetrics, HistoryPoint, MetricsSnapshotInput, MetricsEvent, MetricsAccepted,
    DashboardResponse,
)
from app.services.kafka_producer import MetricsKafkaProducer
from app.services.pinot_client import PinotClient, PinotQueryError

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
dashboard_router = APIRouter(prefix="/api", tags=["dashboard"])

CURRENT_SQL = """
SELECT event_id, event_timestamp, zone_id, online_drivers, ride_requests,
       accepted_requests, cancelled_requests, waiting_drivers
FROM ride_metrics
WHERE zone_id = 'ZONE_1'
ORDER BY event_timestamp DESC
LIMIT 1
"""

HISTORY_SQL = """
SELECT event_timestamp, online_drivers, ride_requests,
       accepted_requests, cancelled_requests, waiting_drivers
FROM ride_metrics
WHERE zone_id = 'ZONE_1'
  AND event_timestamp >= ago('PT1H')
  AND event_timestamp <= now()
ORDER BY event_timestamp ASC
LIMIT 5000
"""


def get_pinot(request: Request) -> PinotClient:
    return request.app.state.pinot


def get_kafka(request: Request) -> MetricsKafkaProducer:
    return request.app.state.kafka


@router.post("", status_code=202, response_model=MetricsAccepted)
async def submit_metrics(
    payload: MetricsSnapshotInput,
    kafka: Annotated[MetricsKafkaProducer, Depends(get_kafka)],
) -> MetricsAccepted:
    event = MetricsEvent(
        **payload.model_dump(), event_id=str(uuid4()),
        event_timestamp=time_ns() // 1_000_000,
    )
    await kafka.publish(event.model_dump())
    return MetricsAccepted(event_id=event.event_id,
                           event_timestamp=event.event_timestamp)


@router.get("/current", response_model=CurrentMetrics)
async def current_metrics(
    pinot: Annotated[PinotClient, Depends(get_pinot)],
    zone_id: Literal["ZONE_1"] = "ZONE_1",
) -> CurrentMetrics:
    rows = await pinot.query(CURRENT_SQL)
    return parse_current(rows)


def parse_current(rows: list[dict]) -> CurrentMetrics:
    if not rows:
        return CurrentMetrics.zero()
    try:
        if any(rows[0].get(field) is None for field in ('zone_id', 'event_id', 'event_timestamp')):
            raise ValueError("Stored snapshot lacks event metadata")
        snapshot = CurrentMetrics.model_validate(rows[0])
        if not snapshot.event_id:
            raise ValueError("Stored snapshot lacks event metadata")
        return snapshot
    except (ValidationError, ValueError) as exc:
        raise PinotQueryError("Invalid current snapshot returned by Pinot") from exc


@router.get("/history", response_model=list[HistoryPoint])
async def metrics_history(
    pinot: Annotated[PinotClient, Depends(get_pinot)],
    zone_id: Literal["ZONE_1"] = "ZONE_1",
    window: Literal["1h"] = "1h",
) -> list[HistoryPoint]:
    rows = await pinot.query(HISTORY_SQL)
    return parse_history(rows)


def parse_history(rows: list[dict]) -> list[HistoryPoint]:
    try:
        return [HistoryPoint.model_validate(row) for row in rows]
    except ValidationError as exc:
        raise PinotQueryError("Invalid history returned by Pinot") from exc


@dashboard_router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    pinot: Annotated[PinotClient, Depends(get_pinot)],
    zone_id: Literal["ZONE_1"] = "ZONE_1",
    window: Literal["1h"] = "1h",
) -> DashboardResponse:
    current_rows, history_rows = await asyncio.gather(
        pinot.query(CURRENT_SQL), pinot.query(HISTORY_SQL),
    )
    return DashboardResponse(current=parse_current(current_rows),
                             history=parse_history(history_rows))
