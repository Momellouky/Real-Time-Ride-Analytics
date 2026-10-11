from dataclasses import dataclass
from enum import StrEnum


class UserState(StrEnum):
    IDLE = 'IDLE'
    WAITING_FOR_DRIVER = 'WAITING_FOR_DRIVER'
    IN_RIDE = 'IN_RIDE'


class DriverState(StrEnum):
    OFFLINE = 'OFFLINE'
    WAITING = 'WAITING'
    ASSIGNED = 'ASSIGNED'


class RideState(StrEnum):
    REQUESTED = 'REQUESTED'
    ACCEPTED = 'ACCEPTED'
    CANCELLED = 'CANCELLED'
    COMPLETED = 'COMPLETED'


@dataclass(slots=True)
class User:
    user_id: str
    state: UserState = UserState.IDLE
    active_ride_id: str | None = None


@dataclass(slots=True)
class Driver:
    driver_id: str
    state: DriverState = DriverState.OFFLINE
    active_ride_id: str | None = None


@dataclass(slots=True)
class Ride:
    ride_id: str
    user_id: str
    state: RideState = RideState.REQUESTED
    driver_id: str | None = None
