import time

from fastapi import APIRouter, HTTPException, Request

from app.api.generator import Generator
from app.models.benchmark import BenchmarkResponse, GeneratorMeasurements, PinotMeasurements
from app.queries.operations import ANALYTICS_OPTIONS, ingestion_metrics
from app.services.pinot_client import PinotQueryError

router = APIRouter(prefix='/api/v2/benchmark', tags=['benchmark'])


def parse_ingestion(rows: list[dict], cutoff: int) -> tuple[int, int | None]:
    try:
        if len(rows) != 1:
            raise ValueError('Expected one ingestion aggregate')
        count = rows[0]['total_ingested_events']
        stamp = rows[0]['latest_event_timestamp']
        if type(count) is not int or count < 0:
            raise ValueError('Invalid ingested event count')
        if count == 0:
            if stamp is not None:
                raise ValueError('Empty run must have a null newest timestamp')
        elif type(stamp) is not int or not 0 <= stamp <= cutoff:
            raise ValueError('Invalid newest event timestamp')
        return count, stamp
    except (KeyError, TypeError, ValueError) as exc:
        raise PinotQueryError('Invalid ingestion aggregate from Pinot') from exc


@router.get('/metrics', response_model=BenchmarkResponse)
async def benchmark_metrics(request: Request, generator: Generator):
    pinot = request.app.state.pinot
    metadata = generator.metadata
    cutoff = time.time_ns() // 1_000_000
    count, stamp = 0, None
    if metadata is not None:
        rows = await pinot.query(ingestion_metrics(metadata.simulation_id, cutoff),
                                 options=ANALYTICS_OPTIONS)
        if generator.metadata is not metadata:
            raise HTTPException(409, 'The simulation run changed. Refresh to load the new run.')
        count, stamp = parse_ingestion(rows, cutoff)
    # Capture runtime counters after query I/O, so a stale producer snapshot does
    # not create a negative backlog when ingestion progresses during the request.
    status = generator.status()
    measurements = GeneratorMeasurements(**{field: status[field]
        for field in GeneratorMeasurements.model_fields})
    now = time.time_ns() // 1_000_000
    return BenchmarkResponse(
        simulation_id=metadata.simulation_id if metadata else None, as_of_ms=cutoff,
        generator=measurements,
        pinot=PinotMeasurements(total_ingested_events=count,
            events_not_yet_visible=max(0, measurements.generated_events - count),
            latest_event_timestamp=stamp,
            ingestion_lag_ms=max(0, now - stamp) if stamp is not None else None,
            query_latency=pinot.metrics.latency_summary()),
        system=request.app.state.system_metrics.snapshot())
