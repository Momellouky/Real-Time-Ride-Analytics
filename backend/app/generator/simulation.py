from collections.abc import Callable
from random import Random
import time
from uuid import uuid4

from .entities import Driver, DriverState, Ride, RideState, User, UserState
from .events import EventType, OperationEvent
from .pools import StatePool


class Simulation:
    """Single-owner mutable state for one run, with no I/O or background work.

    Only active rides are retained. Terminal ride events form the durable history
    once published, keeping generator memory bounded by the configured pools.
    """

    def __init__(self, user_count: int = 10_000, driver_count: int = 2_000, *,
                 seed: int | None = None, clock_ms: Callable[[], int] | None = None):
        for name, value in [('user_count', user_count), ('driver_count', driver_count)]:
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        self.simulation_id = 'sim-' + str(uuid4())
        self.user_pool_size = user_count
        self.driver_pool_size = driver_count
        self.sequence_number = 0
        self._ride_number = 0
        self._last_timestamp = 0
        self.rng = Random(seed)
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.users = {f'user-{i:06d}': User(f'user-{i:06d}') for i in range(1, user_count + 1)}
        self.drivers = {f'driver-{i:06d}': Driver(f'driver-{i:06d}') for i in range(1, driver_count + 1)}
        self.rides: dict[str, Ride] = {}
        self.user_pools = {state: StatePool(self.users if state == UserState.IDLE else ())
                           for state in UserState}
        self.driver_pools = {state: StatePool(self.drivers if state == DriverState.OFFLINE else ())
                             for state in DriverState}
        self.ride_pools = {state: StatePool() for state in (RideState.REQUESTED, RideState.ACCEPTED)}

    def new_ride_id(self) -> str:
        self._ride_number += 1
        return f'ride-{self._ride_number:08d}'

    def build_event(self, event_type: EventType, *, user_id: str | None = None,
                    driver_id: str | None = None, ride_id: str | None = None) -> OperationEvent:
        # Preserve timestamp/sequence latest-state ordering if the wall clock regresses.
        timestamp = max(self._last_timestamp, self._clock_ms())
        self._last_timestamp = timestamp
        self.sequence_number += 1
        return OperationEvent(event_id=str(uuid4()), simulation_id=self.simulation_id,
                              sequence_number=self.sequence_number, event_timestamp=timestamp,
                              event_type=event_type, user_id=user_id,
                              driver_id=driver_id, ride_id=ride_id)

    def move_user(self, user: User, state: UserState) -> None:
        self.user_pools[user.state].remove(user.user_id)
        self.user_pools[state].add(user.user_id)
        user.state = state

    def move_driver(self, driver: Driver, state: DriverState) -> None:
        self.driver_pools[driver.state].remove(driver.driver_id)
        self.driver_pools[state].add(driver.driver_id)
        driver.state = state

    def counts(self) -> dict[str, int]:
        """Runtime diagnostics, not dashboard analytics; all counts are O(1)."""
        return dict(idle_users=len(self.user_pools[UserState.IDLE]),
                    waiting_users=len(self.user_pools[UserState.WAITING_FOR_DRIVER]),
                    users_in_ride=len(self.user_pools[UserState.IN_RIDE]),
                    offline_drivers=len(self.driver_pools[DriverState.OFFLINE]),
                    waiting_drivers=len(self.driver_pools[DriverState.WAITING]),
                    assigned_drivers=len(self.driver_pools[DriverState.ASSIGNED]))

    def check_invariants(self) -> None:
        """Full O(pool size) audit for tests/debugging, not the action hot path."""
        for entities, pools in [(self.users, self.user_pools), (self.drivers, self.driver_pools),
                                (self.rides, self.ride_pools)]:
            indexed = []
            for state, pool in pools.items():
                pool.check_invariants()
                indexed.extend(pool)
                assert all(key in entities and entities[key].state == state for key in pool), 'Wrong state index'
            assert len(indexed) == len(set(indexed)), 'Entity in multiple state pools'
            assert set(indexed) == set(entities), 'Missing entity from state pools'
        assert len(self.users) == self.user_pool_size, 'User population changed'
        assert len(self.drivers) == self.driver_pool_size, 'Driver population changed'
        for user in self.users.values():
            if user.state == UserState.IDLE:
                assert user.active_ride_id is None, 'Idle user has an active ride'
            else:
                ride = self.rides.get(user.active_ride_id)
                assert ride is not None and ride.user_id == user.user_id, 'User/ride link mismatch'
                expected = RideState.REQUESTED if user.state == UserState.WAITING_FOR_DRIVER else RideState.ACCEPTED
                assert ride.state == expected, 'User/ride state mismatch'
        for driver in self.drivers.values():
            if driver.state != DriverState.ASSIGNED:
                assert driver.active_ride_id is None, 'Unassigned driver has an active ride'
            else:
                ride = self.rides.get(driver.active_ride_id)
                assert ride is not None and ride.state == RideState.ACCEPTED, 'Assigned driver missing ride'
                assert ride.driver_id == driver.driver_id, 'Driver/ride link mismatch'
        for ride in self.rides.values():
            user = self.users[ride.user_id]
            assert user.active_ride_id == ride.ride_id, 'Ride/user link mismatch'
            if ride.state == RideState.REQUESTED:
                assert ride.driver_id is None, 'Requested ride already assigned'
            else:
                driver = self.drivers[ride.driver_id]
                assert driver.active_ride_id == ride.ride_id, 'Ride/driver link mismatch'
