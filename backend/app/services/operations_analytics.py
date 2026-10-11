import asyncio
import time

from pydantic import ValidationError

from app.models.operations import (DriverCounts, OperationsAnalyticsResult, RateBucket,
                                   RideBucket, RideCounts)
from app.queries import operations as sql
from app.services.pinot_client import PinotClient, PinotQueryError

RIDE_FIELDS = dict(zip(sql.RIDE_TYPES, ('requested', 'accepted', 'cancelled', 'completed'), strict=True))
DRIVER_FIELDS = dict(zip(sql.DRIVER_TYPES, ('connected', 'waiting', 'assigned', 'disconnected'), strict=True))


def nonnegative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError('Expected a nonnegative integer aggregate')
    return value


def grouped_counts(rows, *, key, count, fields):
    values = {}
    for row in rows:
        kind = row[key]
        if kind not in fields or fields[kind] in values:
            raise ValueError('Invalid or duplicate aggregate group')
        values[fields[kind]] = nonnegative_int(row[count])
    return values


def scalar(rows, field):
    if len(rows) != 1:
        raise ValueError('Expected one scalar aggregate row')
    return nonnegative_int(rows[0][field])


def bucket_timestamp(value, width, lower, upper):
    stamp = nonnegative_int(value)
    if stamp % width or not lower // width * width <= stamp <= upper // width * width:
        raise ValueError('Invalid bucket timestamp')
    return stamp


def parse_ride_history(rows, as_of_ms):
    buckets = {}
    for row in rows:
        stamp = bucket_timestamp(row['time_bucket'], 60_000, as_of_ms - 3_600_000, as_of_ms)
        kind = RIDE_FIELDS.get(row['event_type'])
        if kind is None or kind in buckets.get(stamp, {}):
            raise ValueError('Invalid or duplicate ride history group')
        buckets.setdefault(stamp, {})[kind] = nonnegative_int(row['event_count'])
    return [RideBucket(time_bucket=stamp, **values) for stamp, values in sorted(buckets.items())]


def parse_rate(rows, as_of_ms):
    buckets = {}
    for row in rows:
        stamp = bucket_timestamp(row['time_bucket'], 10_000, as_of_ms - 600_000, as_of_ms)
        if stamp in buckets:
            raise ValueError('Duplicate rate bucket')
        bucket = RateBucket(time_bucket=stamp, event_count=nonnegative_int(row['event_count']),
                            events_per_second=row['events_per_second'])
        if abs(bucket.events_per_second - bucket.event_count / 10.0) > 1e-8:
            raise ValueError('Invalid event rate aggregate')
        buckets[stamp] = bucket
    return [buckets[stamp] for stamp in sorted(buckets)]


class OperationsAnalytics:
    def __init__(self, pinot: PinotClient):
        self._pinot = pinot

    async def read(self, simulation_id: str, *, as_of_ms: int | None = None) -> OperationsAnalyticsResult:
        cutoff = time.time_ns() // 1_000_000 if as_of_ms is None else as_of_ms
        builders = (sql.recent_rides, sql.latest_drivers, sql.active_users,
                    sql.observed_users, sql.ride_history, sql.event_rate)
        # Validate identifiers/time before sending any queries.
        queries = [builder(simulation_id, cutoff) for builder in builders]
        results = await asyncio.gather(*(self._pinot.query(query, options=sql.ANALYTICS_OPTIONS)
                                         for query in queries), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        rides, drivers, active, observed, history, rate = results
        try:
            active_count, observed_count = scalar(active, 'active_users'), scalar(observed, 'observed_users')
            return OperationsAnalyticsResult(
                simulation_id=simulation_id, as_of_ms=cutoff,
                recent_rides=RideCounts(**grouped_counts(rides, key='event_type', count='event_count', fields=RIDE_FIELDS)),
                drivers=DriverCounts(**grouped_counts(drivers, key='latest_driver_event', count='drivers', fields=DRIVER_FIELDS)),
                active_users=active_count, observed_users=observed_count,
                ride_history=parse_ride_history(history, cutoff), event_rate=parse_rate(rate, cutoff))
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise PinotQueryError('Invalid operations aggregates returned by Pinot') from exc
