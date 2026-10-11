from pydantic import BaseModel, Field, computed_field


class RideCounts(BaseModel):
    requested: int = Field(default=0, ge=0, strict=True)
    accepted: int = Field(default=0, ge=0, strict=True)
    cancelled: int = Field(default=0, ge=0, strict=True)
    completed: int = Field(default=0, ge=0, strict=True)


class DriverCounts(BaseModel):
    connected: int = Field(default=0, ge=0, strict=True)
    waiting: int = Field(default=0, ge=0, strict=True)
    assigned: int = Field(default=0, ge=0, strict=True)
    disconnected: int = Field(default=0, ge=0, strict=True)

    @computed_field
    @property
    def online(self) -> int:
        return self.connected + self.waiting + self.assigned

    @computed_field
    @property
    def observed(self) -> int:
        return self.online + self.disconnected


class RideBucket(RideCounts):
    time_bucket: int = Field(ge=0, strict=True)


class RateBucket(BaseModel):
    time_bucket: int = Field(ge=0, strict=True)
    event_count: int = Field(ge=0, strict=True)
    events_per_second: float = Field(ge=0, allow_inf_nan=False)


class OperationsAnalyticsResult(BaseModel):
    simulation_id: str
    as_of_ms: int
    recent_rides: RideCounts
    drivers: DriverCounts
    active_users: int = Field(ge=0, strict=True)
    observed_users: int = Field(ge=0, strict=True)
    ride_history: list[RideBucket]
    event_rate: list[RateBucket]
