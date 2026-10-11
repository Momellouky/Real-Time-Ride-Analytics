from dataclasses import asdict, dataclass
from enum import StrEnum


class EventType(StrEnum):
    RIDE_REQUESTED = 'RIDE_REQUESTED'
    RIDE_ACCEPTED = 'RIDE_ACCEPTED'
    RIDE_CANCELLED = 'RIDE_CANCELLED'
    RIDE_COMPLETED = 'RIDE_COMPLETED'
    DRIVER_CONNECTED = 'DRIVER_CONNECTED'
    DRIVER_WAITING = 'DRIVER_WAITING'
    DRIVER_ASSIGNED = 'DRIVER_ASSIGNED'
    DRIVER_DISCONNECTED = 'DRIVER_DISCONNECTED'


@dataclass(frozen=True, slots=True)
class OperationEvent:
    event_id: str
    simulation_id: str
    sequence_number: int
    event_timestamp: int
    event_type: EventType
    user_id: str | None = None
    driver_id: str | None = None
    ride_id: str | None = None
    event_version: int = 1
    zone_id: str = 'ZONE_1'

    def to_dict(self) -> dict:
        return asdict(self) | {'event_type': self.event_type.value}
