import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.generator import Generator
from app.generator.service import GeneratorState
from app.models.operations import RideBucket, RateBucket
from app.services.operations_analytics import OperationsAnalytics
from app.services.pinot_client import PinotQueryError

router = APIRouter(prefix='/api/v2', tags=['dashboard'])


class RunInfo(BaseModel):
    simulation_id: str
    user_pool_size: int
    driver_pool_size: int
    target_events_per_second: int
    started_at: int


class DashboardMetrics(BaseModel):
    total_users: int = Field(default=0, ge=0)
    active_users: int = Field(default=0, ge=0)
    online_drivers: int = Field(default=0, ge=0)
    waiting_drivers: int = Field(default=0, ge=0)
    ride_requests: int = Field(default=0, ge=0)
    accepted_rides: int = Field(default=0, ge=0)
    cancelled_rides: int = Field(default=0, ge=0)
    completed_rides: int = Field(default=0, ge=0)


class DriverStates(BaseModel):
    connected: int = Field(default=0, ge=0)
    waiting: int = Field(default=0, ge=0)
    assigned: int = Field(default=0, ge=0)
    offline: int = Field(default=0, ge=0)


class DashboardResponse(BaseModel):
    run: RunInfo | None = None
    generator_status: GeneratorState
    generator_error: str | None = None
    as_of_ms: int
    metrics: DashboardMetrics = Field(default_factory=DashboardMetrics)
    driver_states: DriverStates = Field(default_factory=DriverStates)
    observed_users: int = 0
    ride_history: list[RideBucket] = Field(default_factory=list)
    event_rate: list[RateBucket] = Field(default_factory=list)


@router.get('/dashboard', response_model=DashboardResponse)
async def dashboard(request: Request, generator: Generator):
    metadata = generator.metadata
    cutoff = time.time_ns() // 1_000_000
    if metadata is None:
        return DashboardResponse(generator_status=generator.state, as_of_ms=cutoff)
    result = await OperationsAnalytics(request.app.state.pinot).read(
        metadata.simulation_id, as_of_ms=cutoff)
    if generator.metadata is not metadata:
        raise HTTPException(409, 'The simulation run changed. Refresh to load the new run.')
    drivers = result.drivers
    if (drivers.observed > metadata.driver_pool_size or
            max(result.active_users, result.observed_users) > metadata.user_pool_size):
        raise PinotQueryError('Analytics exceed the configured run population')
    rides = result.recent_rides
    return DashboardResponse(
        run=RunInfo(**asdict(metadata)), generator_status=generator.state,
        generator_error=generator.last_error, as_of_ms=cutoff,
        metrics=DashboardMetrics(total_users=metadata.user_pool_size,
            active_users=result.active_users, online_drivers=drivers.online,
            waiting_drivers=drivers.waiting, ride_requests=rides.requested,
            accepted_rides=rides.accepted, cancelled_rides=rides.cancelled,
            completed_rides=rides.completed),
        driver_states=DriverStates(connected=drivers.connected, waiting=drivers.waiting,
            assigned=drivers.assigned, offline=metadata.driver_pool_size - drivers.online),
        observed_users=result.observed_users, ride_history=result.ride_history,
        event_rate=result.event_rate)
