from dataclasses import FrozenInstanceError, asdict
import json
from random import Random
from uuid import UUID

import pytest

from app.generator import Simulation
from app.generator.actions import (ACTIONS, accept_ride, cancel_ride, choose_action,
                                   complete_ride, connect_driver, disconnect_driver,
                                   execute_action, request_ride, valid_actions)
from app.generator.entities import DriverState, RideState, UserState
from app.generator.events import EventType
from app.generator.pools import StatePool


USER = 'user-000001'
DRIVER = 'driver-000001'


def snapshot(sim):
    return (sim.sequence_number, sim._ride_number,
            [asdict(user) for user in sim.users.values()],
            [asdict(driver) for driver in sim.drivers.values()],
            [asdict(ride) for ride in sim.rides.values()],
            [list(pool) for pools in (sim.user_pools, sim.driver_pools, sim.ride_pools)
             for pool in pools.values()])


def requested(sim):
    return request_ride(sim, USER)[0].ride_id


def accepted(sim):
    connect_driver(sim, DRIVER)
    ride_id = requested(sim)
    accept_ride(sim, ride_id, DRIVER)
    return ride_id


@pytest.mark.parametrize('field', ['user_count', 'driver_count'])
@pytest.mark.parametrize('value', [0, -1, True, 1.5, '10', None])
def test_pool_size_requires_positive_integer(field, value):
    with pytest.raises(ValueError, match='positive integer'):
        Simulation(**{field: value})


def test_default_population_and_fresh_runs_are_independent():
    first, second = Simulation(), Simulation()
    assert first.simulation_id != second.simulation_id
    assert UUID(first.simulation_id.removeprefix('sim-')).version == 4
    assert first.sequence_number == second.sequence_number == 0
    assert first.counts() == dict(idle_users=10_000, waiting_users=0, users_in_ride=0,
                                 offline_drivers=2_000, waiting_drivers=0, assigned_drivers=0)
    request_ride(first, USER)
    assert second.users[USER].state == UserState.IDLE
    first.check_invariants()
    second.check_invariants()


def test_complete_lifecycle_event_envelopes_and_links():
    sim = Simulation(1, 1, clock_ms=lambda: 1234)
    events = connect_driver(sim, DRIVER)
    assert sim.drivers[DRIVER].state == DriverState.WAITING
    events += request_ride(sim, USER)
    ride_id = events[-1].ride_id
    assert sim.users[USER].active_ride_id == ride_id
    assert sim.rides[ride_id].state == RideState.REQUESTED
    events += accept_ride(sim, ride_id, DRIVER)
    assert sim.rides[ride_id].driver_id == DRIVER
    assert sim.drivers[DRIVER].active_ride_id == ride_id
    assert sim.users[USER].state == UserState.IN_RIDE
    sim.check_invariants()
    events += complete_ride(sim, ride_id)
    assert sim.users[USER].state == UserState.IDLE
    assert sim.drivers[DRIVER].state == DriverState.WAITING
    assert sim.users[USER].active_ride_id is None
    assert sim.drivers[DRIVER].active_ride_id is None
    assert ride_id not in sim.rides
    events += disconnect_driver(sim, DRIVER)
    assert [event.event_type for event in events] == [
        EventType.DRIVER_CONNECTED, EventType.DRIVER_WAITING, EventType.RIDE_REQUESTED,
        EventType.RIDE_ACCEPTED, EventType.DRIVER_ASSIGNED, EventType.RIDE_COMPLETED,
        EventType.DRIVER_WAITING, EventType.DRIVER_DISCONNECTED]
    assert [event.sequence_number for event in events] == list(range(1, 9))
    assert len({event.event_id for event in events}) == len(events)
    for event in events:
        assert UUID(event.event_id).version == 4
        assert event.simulation_id == sim.simulation_id
        assert event.event_timestamp == 1234
        assert event.zone_id == 'ZONE_1' and event.event_version == 1
        wire = json.loads(json.dumps(event.to_dict()))
        assert set(wire) == {'event_id', 'event_version', 'simulation_id', 'sequence_number',
                             'event_timestamp', 'event_type', 'zone_id', 'user_id', 'driver_id', 'ride_id'}
        assert wire['event_type'] == event.event_type.value
    assert events[0].user_id is None and events[0].ride_id is None
    assert events[6].user_id is None and events[6].ride_id == ride_id
    with pytest.raises(FrozenInstanceError):
        events[0].driver_id = 'different-driver'
    sim.check_invariants()


def test_cancellation_releases_user_and_does_not_reuse_ride_ids():
    sim = Simulation(1, 1)
    first = requested(sim)
    events = cancel_ride(sim, first)
    assert events[0].event_type == EventType.RIDE_CANCELLED
    assert events[0].driver_id is None
    assert sim.users[USER].active_ride_id is None
    assert not sim.rides
    second = requested(sim)
    assert second != first
    sim.check_invariants()


@pytest.mark.parametrize('in_ride', [False, True])
def test_non_idle_user_cannot_request_twice(in_ride):
    sim = Simulation(1, 1)
    accepted(sim) if in_ride else requested(sim)
    before = snapshot(sim)
    assert request_ride(sim, USER) == []
    assert request_ride(sim) == []
    assert snapshot(sim) == before
    sim.check_invariants()


def test_accepted_ride_cannot_cancel_or_accept_twice_and_assigned_driver_cannot_disconnect():
    sim = Simulation(1, 1)
    ride_id = accepted(sim)
    before = snapshot(sim)
    assert cancel_ride(sim, ride_id) == []
    assert accept_ride(sim, ride_id, DRIVER) == []
    assert disconnect_driver(sim, DRIVER) == []
    assert connect_driver(sim, DRIVER) == []
    assert snapshot(sim) == before
    sim.check_invariants()


def test_accept_requires_waiting_driver_and_one_driver_cannot_serve_two_rides():
    sim = Simulation(2, 1)
    first = requested(sim)
    before = snapshot(sim)
    assert accept_ride(sim, first, DRIVER) == []
    assert snapshot(sim) == before
    connect_driver(sim, DRIVER)
    accept_ride(sim, first, DRIVER)
    second = request_ride(sim, 'user-000002')[0].ride_id
    before = snapshot(sim)
    assert accept_ride(sim, second, DRIVER) == []
    assert snapshot(sim) == before
    complete_ride(sim, first)
    assert len(accept_ride(sim, second, DRIVER)) == 2
    sim.check_invariants()


def test_requested_ride_cannot_complete_and_terminal_actions_cannot_repeat():
    sim = Simulation(1, 1)
    ride_id = requested(sim)
    before = snapshot(sim)
    assert complete_ride(sim, ride_id) == []
    assert snapshot(sim) == before
    cancel_ride(sim, ride_id)
    before = snapshot(sim)
    assert cancel_ride(sim, ride_id) == accept_ride(sim, ride_id) == complete_ride(sim, ride_id) == []
    assert snapshot(sim) == before
    ride_id = accepted(sim)
    complete_ride(sim, ride_id)
    before = snapshot(sim)
    assert complete_ride(sim, ride_id) == []
    assert snapshot(sim) == before


@pytest.mark.parametrize('action', [connect_driver, disconnect_driver, request_ride,
                                    cancel_ride, accept_ride, complete_ride])
def test_unknown_entity_is_noop(action):
    sim = Simulation(1, 1)
    before = snapshot(sim)
    assert action(sim, 'unknown') == []
    assert snapshot(sim) == before


def test_selection_filters_preconditions_and_event_budget():
    sim = Simulation(1, 1, seed=1)
    assert {action.name for action in valid_actions(sim)} == {'connect_driver', 'request_ride'}
    assert choose_action(sim, event_budget=0) is None
    assert choose_action(sim, event_budget=1).name == 'request_ride'
    requested(sim)
    assert {a.name for a in valid_actions(sim)} == {'connect_driver', 'cancel_ride'}
    connect_driver(sim, DRIVER)
    assert {a.name for a in valid_actions(sim)} == {'accept_ride', 'cancel_ride', 'disconnect_driver'}
    accept_ride(sim)
    assert [a.name for a in valid_actions(sim)] == ['complete_ride']
    assert choose_action(sim, event_budget=1) is None
    action = choose_action(sim, event_budget=2)
    assert len(execute_action(sim, action)) == action.event_cost == 2
    assert {a.name: a.weight for a in ACTIONS} == dict(request_ride=30, accept_ride=25,
        complete_ride=20, cancel_ride=5, connect_driver=12, disconnect_driver=8)


def test_clock_regression_keeps_timestamp_sequence_order():
    clock = iter([1000, 1000, 900, 1100])
    sim = Simulation(1, 1, clock_ms=lambda: next(clock))
    events = connect_driver(sim) + request_ride(sim) + cancel_ride(sim)
    assert [event.event_timestamp for event in events] == [1000, 1000, 1000, 1100]
    assert [event.sequence_number for event in events] == [1, 2, 3, 4]


def test_state_pool_swap_removal_random_access_and_duplicate_guard():
    pool = StatePool(['a', 'b', 'c', 'd'])
    for value in ('b', 'd', 'a', 'c'):
        pool.remove(value)
        pool.check_invariants()
        assert value not in pool
        assert pool.choose(Random(42)) in pool if len(pool) else pool.choose(Random(42)) is None
    pool.add('new')
    with pytest.raises(ValueError):
        pool.add('new')
    with pytest.raises(KeyError):
        pool.remove('missing')
    pool.check_invariants()


def test_invariant_audit_detects_corrupt_relationship():
    sim = Simulation(1, 1)
    accepted(sim)
    sim.drivers[DRIVER].active_ride_id = 'missing'
    with pytest.raises(AssertionError, match='Assigned driver missing ride'):
        sim.check_invariants()


@pytest.mark.parametrize('seed', [0, 1, 42, 99, 2026])
def test_randomized_actions_replay_to_identical_state(seed):
    """Independent event projection checks every transition, not only final counts."""
    sim = Simulation(23, 7, seed=seed, clock_ms=lambda: 1000)
    users = {key: 'IDLE' for key in sim.users}
    drivers = {key: 'OFFLINE' for key in sim.drivers}
    rides = {}
    user_ride, driver_ride = {}, {}
    seen_ids, types = set(), set()
    sequence = 0
    for _ in range(2000):
        action = choose_action(sim)
        assert action is not None
        events = execute_action(sim, action)
        assert len(events) == action.event_cost
        for event in events:
            sequence += 1
            assert event.sequence_number == sequence
            assert event.event_id not in seen_ids
            seen_ids.add(event.event_id)
            types.add(event.event_type)
            u, d, r, kind = event.user_id, event.driver_id, event.ride_id, event.event_type
            if kind == EventType.DRIVER_CONNECTED:
                assert drivers[d] == 'OFFLINE'
                drivers[d] = 'CONNECTED'
            elif kind == EventType.DRIVER_WAITING:
                assert drivers[d] in ('CONNECTED', 'ASSIGNED')
                if drivers[d] == 'ASSIGNED':
                    assert rides[r]['state'] == 'COMPLETED' and driver_ride.pop(d) == r
                drivers[d] = 'WAITING'
            elif kind == EventType.DRIVER_DISCONNECTED:
                assert drivers[d] == 'WAITING' and d not in driver_ride
                drivers[d] = 'OFFLINE'
            elif kind == EventType.RIDE_REQUESTED:
                assert users[u] == 'IDLE' and u not in user_ride and r not in rides
                users[u] = 'WAITING_FOR_DRIVER'
                user_ride[u] = r
                rides[r] = {'state': 'REQUESTED', 'user': u, 'driver': None}
            elif kind == EventType.RIDE_CANCELLED:
                assert rides[r]['state'] == 'REQUESTED' and user_ride.pop(u) == r
                assert users[u] == 'WAITING_FOR_DRIVER'
                rides[r]['state'] = 'CANCELLED'
                users[u] = 'IDLE'
            elif kind == EventType.RIDE_ACCEPTED:
                assert rides[r]['state'] == 'REQUESTED' and users[u] == 'WAITING_FOR_DRIVER'
                assert drivers[d] == 'WAITING' and d not in driver_ride
                assert user_ride[u] == r
                users[u] = 'IN_RIDE'
                rides[r].update(state='ACCEPTED', driver=d)
            elif kind == EventType.DRIVER_ASSIGNED:
                assert drivers[d] == 'WAITING' and d not in driver_ride
                assert rides[r]['state'] == 'ACCEPTED' and rides[r]['driver'] == d
                driver_ride[d] = r
                drivers[d] = 'ASSIGNED'
            elif kind == EventType.RIDE_COMPLETED:
                assert rides[r]['state'] == 'ACCEPTED' and users[u] == 'IN_RIDE'
                assert user_ride.pop(u) == r and driver_ride[d] == r
                assert drivers[d] == 'ASSIGNED'
                rides[r]['state'] = 'COMPLETED'
                users[u] = 'IDLE'
        sim.check_invariants()
        assert {key: user.state.value for key, user in sim.users.items()} == users
        assert {key: driver.state.value for key, driver in sim.drivers.items()} == drivers
        assert {key: user.active_ride_id for key, user in sim.users.items()
                if user.active_ride_id is not None} == user_ride
        assert {key: driver.active_ride_id for key, driver in sim.drivers.items()
                if driver.active_ride_id is not None} == driver_ride
        assert set(sim.rides) == {key for key, ride in rides.items()
                                  if ride['state'] in ('REQUESTED', 'ACCEPTED')}
        assert len(sim.rides) <= sim.user_pool_size
    assert types == set(EventType)


def test_repeated_terminal_rides_do_not_accumulate_in_memory():
    sim = Simulation(1, 1)
    connect_driver(sim)
    for _ in range(1000):
        ride_id = requested(sim)
        accept_ride(sim, ride_id)
        complete_ride(sim, ride_id)
        assert not sim.rides and not len(sim.ride_pools[RideState.ACCEPTED])
    assert sim.sequence_number == 5002
    sim.check_invariants()
