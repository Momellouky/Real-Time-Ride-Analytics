from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricValues(BaseModel):
    online_drivers: int = Field(ge=0, strict=True)
    ride_requests: int = Field(ge=0, strict=True)
    accepted_requests: int = Field(ge=0, strict=True)
    cancelled_requests: int = Field(ge=0, strict=True)
    waiting_drivers: int = Field(ge=0, strict=True)


class CurrentMetrics(MetricValues):
    zone_id: Literal["ZONE_1"] = "ZONE_1"
    event_id: str | None = None
    event_timestamp: int | None = Field(default=None, ge=0, strict=True)

    @classmethod
    def zero(cls):
        return cls(online_drivers=0, ride_requests=0, accepted_requests=0,
                   cancelled_requests=0, waiting_drivers=0)


class HistoryPoint(MetricValues):
    event_timestamp: int = Field(ge=0, strict=True)


class DashboardResponse(BaseModel):
    current: CurrentMetrics
    history: list[HistoryPoint]


class MetricsSnapshotInput(MetricValues):
    zone_id: Literal["ZONE_1"]
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_business_rules(self):
        for field in MetricValues.model_fields:
            if getattr(self, field) > 2_147_483_647:
                raise ValueError(f"{field} must be <= 2147483647 (Pinot INT maximum)")
        if self.accepted_requests + self.cancelled_requests > self.ride_requests:
            raise ValueError("accepted_requests + cancelled_requests must be <= ride_requests")
        if self.waiting_drivers > self.online_drivers:
            raise ValueError("waiting_drivers must be <= online_drivers")
        return self


class MetricsEvent(MetricsSnapshotInput):
    event_id: str
    event_timestamp: int = Field(ge=0, strict=True)


class MetricsAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"
    event_id: str
    event_timestamp: int
