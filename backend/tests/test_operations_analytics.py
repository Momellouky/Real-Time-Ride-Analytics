from unittest.mock import AsyncMock

import httpx
import pytest

from app.queries import operations as sql
from app.services.operations_analytics import OperationsAnalytics
from app.services.pinot_client import PinotClient, PinotQueryError

NOW = 1_800_000_000_000
BUILDERS = [sql.recent_rides, sql.ride_history, sql.latest_drivers, sql.active_users,
            sql.observed_users, sql.event_rate]


@pytest.mark.parametrize('builder', BUILDERS)
def test_all_queries_isolate_run_zone_and_future_events(builder):
    query = builder('sim-test', NOW)
    assert "simulation_id = 'sim-test'" in query
    assert "zone_id = 'ZONE_1'" in query
    assert f'event_timestamp <= {NOW}' in query


@pytest.mark.parametrize('identifier', ["x' OR 1=1 --", '', 'x;DROP TABLE operations', None, 'x' * 129])
def test_unsafe_run_identifiers_never_reach_pinot(identifier):
    with pytest.raises(ValueError, match='simulation_id'):
        sql.latest_drivers(identifier, NOW)


@pytest.mark.parametrize('timestamp', [True, 1.5, '123', None, -1, 0])
def test_invalid_cutoff_rejected(timestamp):
    with pytest.raises(ValueError, match='as_of_ms'):
        sql.active_users('sim-test', timestamp)


def test_state_is_all_run_and_rates_use_event_counts_in_bounded_windows():
    for builder in (sql.latest_drivers, sql.active_users, sql.observed_users):
        assert 'event_timestamp >=' not in builder('sim-test', NOW)
    assert "LASTWITHTIME(event_type, sequence_number, 'STRING')" in sql.latest_drivers('sim-test', NOW)
    assert 'driver_id IS NOT NULL' in sql.latest_drivers('sim-test', NOW)
    assert 'user_id IS NOT NULL' in sql.observed_users('sim-test', NOW)
    assert str(NOW - 60_000) in sql.recent_rides('sim-test', NOW)
    assert "'1:MINUTES'" in sql.ride_history('sim-test', NOW)
    assert str(NOW - 3_600_000) in sql.ride_history('sim-test', NOW)
    assert "'10:SECONDS'" in sql.event_rate('sim-test', NOW)
    assert 'COUNT(*) / 10.0' in sql.event_rate('sim-test', NOW)


def pinot_with(responses=None):
    rows = responses or [[], [], [{'active_users': 0}], [{'observed_users': 0}], [], []]
    return AsyncMock(query=AsyncMock(side_effect=rows))


async def test_empty_run_returns_zero_aggregates_and_no_fabricated_points():
    pinot = pinot_with()
    result = await OperationsAnalytics(pinot).read('sim-empty', as_of_ms=NOW)
    assert result.recent_rides.model_dump() == dict(requested=0, accepted=0, cancelled=0, completed=0)
    assert result.drivers.online == result.drivers.observed == result.active_users == result.observed_users == 0
    assert result.ride_history == result.event_rate == []
    assert pinot.query.await_count == 6
    assert all(call.kwargs['options'] == sql.ANALYTICS_OPTIONS for call in pinot.query.await_args_list)
    assert all(f'event_timestamp <= {NOW}' in call.args[0] for call in pinot.query.await_args_list)


async def test_aggregates_map_to_typed_counts_and_sorted_buckets():
    pinot = pinot_with([
        [{'event_type': 'RIDE_REQUESTED', 'event_count': 2}],
        [{'latest_driver_event': 'DRIVER_CONNECTED', 'drivers': 1},
         {'latest_driver_event': 'DRIVER_WAITING', 'drivers': 2},
         {'latest_driver_event': 'DRIVER_ASSIGNED', 'drivers': 3},
         {'latest_driver_event': 'DRIVER_DISCONNECTED', 'drivers': 4}],
        [{'active_users': 7}], [{'observed_users': 10}],
        [{'time_bucket': NOW, 'event_type': 'RIDE_CANCELLED', 'event_count': 1},
         {'time_bucket': NOW - 60_000, 'event_type': 'RIDE_REQUESTED', 'event_count': 5},
         {'time_bucket': NOW, 'event_type': 'RIDE_COMPLETED', 'event_count': 2}],
        [{'time_bucket': NOW, 'event_count': 20, 'events_per_second': 2.0}]
    ])
    result = await OperationsAnalytics(pinot).read('sim-test', as_of_ms=NOW)
    assert result.drivers.online == 6 and result.drivers.observed == 10
    assert result.active_users == 7 and result.observed_users == 10
    assert [bucket.time_bucket for bucket in result.ride_history] == [NOW - 60_000, NOW]
    assert result.ride_history[1].cancelled == 1 and result.ride_history[1].completed == 2
    assert result.event_rate[0].events_per_second == 2


@pytest.mark.parametrize('position,rows', [
    (0, [{'event_type': 'UNKNOWN', 'event_count': 1}]),
    (0, [{'event_type': 'RIDE_REQUESTED', 'event_count': -1}]),
    (0, [{'event_type': 'RIDE_REQUESTED', 'event_count': '1'}]),
    (1, [{'latest_driver_event': 'DRIVER_WAITING', 'drivers': 1}] * 2),
    (2, []), (3, [{'observed_users': True}]),
    (4, [{'time_bucket': NOW + 60_000, 'event_type': 'RIDE_REQUESTED', 'event_count': 1}]),
    (4, [{'time_bucket': NOW + 1, 'event_type': 'RIDE_REQUESTED', 'event_count': 1}]),
    (4, [{'time_bucket': NOW, 'event_type': 'RIDE_REQUESTED', 'event_count': 1}] * 2),
    (5, [{'time_bucket': NOW, 'event_count': 10, 'events_per_second': 100.0}]),
    (5, [{'time_bucket': NOW, 'event_count': 1, 'events_per_second': float('nan')}]),
    (5, [{'time_bucket': NOW, 'event_count': 10, 'events_per_second': 1.0}] * 2),
])
async def test_invalid_aggregates_are_errors_not_empty_results(position, rows):
    responses = [[], [], [{'active_users': 0}], [{'observed_users': 0}], [], []]
    responses[position] = rows
    with pytest.raises(PinotQueryError, match='Invalid operations aggregates'):
        await OperationsAnalytics(pinot_with(responses)).read('sim-test', as_of_ms=NOW)


async def test_invalid_run_sends_nothing_and_query_failure_propagates():
    pinot = pinot_with()
    with pytest.raises(ValueError):
        await OperationsAnalytics(pinot).read("invalid'", as_of_ms=NOW)
    pinot.query.assert_not_awaited()
    pinot.query.side_effect = PinotQueryError('query failed')
    with pytest.raises(PinotQueryError):
        await OperationsAnalytics(pinot).read('sim-test', as_of_ms=NOW)


async def test_client_passes_multi_stage_options_without_changing_v1_default():
    seen = []
    def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'resultTable': {'dataSchema': {'columnNames': ['count']}, 'rows': [[0]]}})
    client = PinotClient('http://broker', transport=httpx.MockTransport(handler))
    try:
        await client.query('SELECT v1')
        await client.query('SELECT v2', options=sql.ANALYTICS_OPTIONS)
    finally:
        await client.close()
    assert seen == [{'sql': 'SELECT v1'}, {'sql': 'SELECT v2', 'queryOptions': 'useMultistageEngine=true;enableNullHandling=true'}]


@pytest.mark.parametrize('flag', ['numGroupsLimitReached', 'groupsTrimmed', 'maxRowsInJoinReached', 'maxRowsInWindowReached'])
async def test_truncation_flags_reject_plausible_aggregate_rows(flag):
    client = PinotClient('http://broker', transport=httpx.MockTransport(lambda request:
        httpx.Response(200, json={flag: True, 'resultTable': {'dataSchema': {'columnNames': ['count']}, 'rows': [[1]]}})))
    try:
        with pytest.raises(PinotQueryError):
            await client.query('SELECT test')
    finally:
        await client.close()
