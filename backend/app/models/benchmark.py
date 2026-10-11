from typing import Literal

from pydantic import BaseModel, Field

from app.generator.service import GeneratorState


class GeneratorMeasurements(BaseModel):
    status: GeneratorState
    target_events_per_second: int = Field(ge=0, strict=True)
    actual_events_per_second: float = Field(ge=0, allow_inf_nan=False)
    generated_events: int = Field(ge=0, strict=True)
    published_events: int = Field(ge=0, strict=True)
    last_error: str | None = None


class QueryLatency(BaseModel):
    avg_ms: float = Field(ge=0, allow_inf_nan=False)
    p95_ms: float = Field(ge=0, allow_inf_nan=False)
    p99_ms: float = Field(ge=0, allow_inf_nan=False)
    sample_count: int = Field(ge=0, le=500, strict=True)


class PinotMeasurements(BaseModel):
    total_ingested_events: int = Field(default=0, ge=0, strict=True)
    events_not_yet_visible: int = Field(default=0, ge=0, strict=True)
    latest_event_timestamp: int | None = Field(default=None, ge=0, strict=True)
    ingestion_lag_ms: int | None = Field(default=None, ge=0, strict=True)
    query_latency: QueryLatency


class SystemMeasurements(BaseModel):
    sampled_at_ms: int = Field(ge=0, strict=True)
    cpu_percent: float | None = Field(ge=0, le=100, allow_inf_nan=False)
    memory_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    memory_used_gb: float = Field(ge=0, allow_inf_nan=False)
    memory_total_gb: float = Field(gt=0, allow_inf_nan=False)
    scope: Literal['os_visible_to_backend']


class BenchmarkResponse(BaseModel):
    simulation_id: str | None
    as_of_ms: int = Field(ge=0, strict=True)
    generator: GeneratorMeasurements
    pinot: PinotMeasurements
    system: SystemMeasurements | None
