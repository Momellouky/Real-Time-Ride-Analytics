"""Valid business actions. Rejected actions return no events and change no state."""
from dataclasses import dataclass

from .entities import DriverState, Ride, RideState, UserState
from .events import EventType as E, OperationEvent
from .simulation import Simulation


def connect_driver(sim: Simulation, driver_id: str | None = None) -> list[OperationEvent]:
    key = driver_id if driver_id is not None else sim.driver_pools[DriverState.OFFLINE].choose(sim.rng)
    driver = sim.drivers.get(key)
    if driver is None or driver.state != DriverState.OFFLINE:
        return []
    sim.move_driver(driver, DriverState.WAITING)
    return [sim.build_event(E.DRIVER_CONNECTED, driver_id=key),
            sim.build_event(E.DRIVER_WAITING, driver_id=key)]


def disconnect_driver(sim: Simulation, driver_id: str | None = None) -> list[OperationEvent]:
    key = driver_id if driver_id is not None else sim.driver_pools[DriverState.WAITING].choose(sim.rng)
    driver = sim.drivers.get(key)
    if driver is None or driver.state != DriverState.WAITING:
        return []
    sim.move_driver(driver, DriverState.OFFLINE)
    return [sim.build_event(E.DRIVER_DISCONNECTED, driver_id=key)]


def request_ride(sim: Simulation, user_id: str | None = None) -> list[OperationEvent]:
    key = user_id if user_id is not None else sim.user_pools[UserState.IDLE].choose(sim.rng)
    user = sim.users.get(key)
    if user is None or user.state != UserState.IDLE:
        return []
    ride = Ride(sim.new_ride_id(), key)
    sim.rides[ride.ride_id] = ride
    sim.ride_pools[RideState.REQUESTED].add(ride.ride_id)
    user.active_ride_id = ride.ride_id
    sim.move_user(user, UserState.WAITING_FOR_DRIVER)
    return [sim.build_event(E.RIDE_REQUESTED, user_id=key, ride_id=ride.ride_id)]


def cancel_ride(sim: Simulation, ride_id: str | None = None) -> list[OperationEvent]:
    key = ride_id if ride_id is not None else sim.ride_pools[RideState.REQUESTED].choose(sim.rng)
    ride = sim.rides.get(key)
    if ride is None or ride.state != RideState.REQUESTED:
        return []
    user = sim.users[ride.user_id]
    user.active_ride_id = None
    sim.move_user(user, UserState.IDLE)
    sim.ride_pools[RideState.REQUESTED].remove(key)
    ride.state = RideState.CANCELLED
    del sim.rides[key]
    return [sim.build_event(E.RIDE_CANCELLED, user_id=user.user_id, ride_id=key)]


def accept_ride(sim: Simulation, ride_id: str | None = None,
                driver_id: str | None = None) -> list[OperationEvent]:
    key = ride_id if ride_id is not None else sim.ride_pools[RideState.REQUESTED].choose(sim.rng)
    driver_key = driver_id if driver_id is not None else sim.driver_pools[DriverState.WAITING].choose(sim.rng)
    ride, driver = sim.rides.get(key), sim.drivers.get(driver_key)
    if (ride is None or ride.state != RideState.REQUESTED
            or driver is None or driver.state != DriverState.WAITING):
        return []
    user = sim.users[ride.user_id]
    sim.ride_pools[RideState.REQUESTED].remove(key)
    sim.ride_pools[RideState.ACCEPTED].add(key)
    ride.state, ride.driver_id = RideState.ACCEPTED, driver_key
    sim.move_user(user, UserState.IN_RIDE)
    driver.active_ride_id = key
    sim.move_driver(driver, DriverState.ASSIGNED)
    return [sim.build_event(E.RIDE_ACCEPTED, user_id=user.user_id, driver_id=driver_key, ride_id=key),
            sim.build_event(E.DRIVER_ASSIGNED, user_id=user.user_id, driver_id=driver_key, ride_id=key)]


def complete_ride(sim: Simulation, ride_id: str | None = None) -> list[OperationEvent]:
    key = ride_id if ride_id is not None else sim.ride_pools[RideState.ACCEPTED].choose(sim.rng)
    ride = sim.rides.get(key)
    if ride is None or ride.state != RideState.ACCEPTED:
        return []
    user, driver = sim.users[ride.user_id], sim.drivers[ride.driver_id]
    user.active_ride_id = None
    driver.active_ride_id = None
    sim.move_user(user, UserState.IDLE)
    sim.move_driver(driver, DriverState.WAITING)
    sim.ride_pools[RideState.ACCEPTED].remove(key)
    ride.state = RideState.COMPLETED
    del sim.rides[key]
    return [sim.build_event(E.RIDE_COMPLETED, user_id=user.user_id, driver_id=driver.driver_id, ride_id=key),
            sim.build_event(E.DRIVER_WAITING, driver_id=driver.driver_id, ride_id=key)]


@dataclass(frozen=True)
class Action:
    name: str
    weight: int
    event_cost: int


ACTIONS = (
    Action('request_ride', 30, 1), Action('accept_ride', 25, 2),
    Action('complete_ride', 20, 2), Action('cancel_ride', 5, 1),
    Action('connect_driver', 12, 2), Action('disconnect_driver', 8, 1),
)


def valid_actions(sim: Simulation, *, event_budget: int | None = None) -> list[Action]:
    available = {
        'request_ride': bool(len(sim.user_pools[UserState.IDLE])),
        'accept_ride': bool(len(sim.ride_pools[RideState.REQUESTED]) and len(sim.driver_pools[DriverState.WAITING])),
        'complete_ride': bool(len(sim.ride_pools[RideState.ACCEPTED])),
        'cancel_ride': bool(len(sim.ride_pools[RideState.REQUESTED])),
        'connect_driver': bool(len(sim.driver_pools[DriverState.OFFLINE])),
        'disconnect_driver': bool(len(sim.driver_pools[DriverState.WAITING])),
    }
    return [action for action in ACTIONS if available[action.name]
            and (event_budget is None or action.event_cost <= event_budget)]


def choose_action(sim: Simulation, *, event_budget: int | None = None) -> Action | None:
    candidates = valid_actions(sim, event_budget=event_budget)
    return sim.rng.choices(candidates, weights=[a.weight for a in candidates], k=1)[0] if candidates else None


def execute_action(sim: Simulation, action: Action) -> list[OperationEvent]:
    handlers = {'request_ride': request_ride, 'accept_ride': accept_ride,
                'complete_ride': complete_ride, 'cancel_ride': cancel_ride,
                'connect_driver': connect_driver, 'disconnect_driver': disconnect_driver}
    return handlers[action.name](sim)
