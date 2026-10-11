"""Bounded analytical queries; run identifiers are validated before interpolation."""
import re

RIDE_TYPES = ('RIDE_REQUESTED', 'RIDE_ACCEPTED', 'RIDE_CANCELLED', 'RIDE_COMPLETED')
DRIVER_TYPES = ('DRIVER_CONNECTED', 'DRIVER_WAITING', 'DRIVER_ASSIGNED', 'DRIVER_DISCONNECTED')
ANALYTICS_OPTIONS = {'useMultistageEngine': 'true', 'enableNullHandling': 'true'}


def run_filter(simulation_id: str, as_of_ms: int) -> str:
    if not isinstance(simulation_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', simulation_id):
        raise ValueError('Invalid simulation_id')
    if type(as_of_ms) is not int or as_of_ms < 3_600_000:
        raise ValueError('as_of_ms must be epoch milliseconds greater than one hour')
    return f"simulation_id = '{simulation_id}' AND zone_id = 'ZONE_1' AND event_timestamp <= {as_of_ms}"


def types(values: tuple[str, ...]) -> str:
    return ','.join(f"'{value}'" for value in values)


def recent_rides(simulation_id: str, as_of_ms: int) -> str:
    return f"""SELECT event_type, COUNT(*) AS event_count FROM operations
WHERE {run_filter(simulation_id, as_of_ms)} AND event_timestamp >= {as_of_ms - 60_000}
AND event_type IN ({types(RIDE_TYPES)}) GROUP BY event_type LIMIT 4"""


def ride_history(simulation_id: str, as_of_ms: int) -> str:
    return f"""SELECT DATETIMECONVERT(event_timestamp, '1:MILLISECONDS:EPOCH',
'1:MILLISECONDS:EPOCH', '1:MINUTES') AS time_bucket, event_type, COUNT(*) AS event_count
FROM operations WHERE {run_filter(simulation_id, as_of_ms)}
AND event_timestamp >= {as_of_ms - 3_600_000} AND event_type IN ({types(RIDE_TYPES)})
GROUP BY time_bucket, event_type ORDER BY time_bucket ASC, event_type ASC LIMIT 1000"""


def latest_drivers(simulation_id: str, as_of_ms: int) -> str:
    # Valid generator runs have non-decreasing timestamps and unique increasing
    # sequences. LASTWITHTIME on sequence resolves same-millisecond transitions.
    return f"""SELECT latest_driver_event, COUNT(*) AS drivers FROM (
SELECT driver_id, LASTWITHTIME(event_type, sequence_number, 'STRING') AS latest_driver_event
FROM operations WHERE {run_filter(simulation_id, as_of_ms)} AND driver_id IS NOT NULL
AND event_type IN ({types(DRIVER_TYPES)}) GROUP BY driver_id)
GROUP BY latest_driver_event LIMIT 4"""


def active_users(simulation_id: str, as_of_ms: int) -> str:
    return f"""SELECT COUNT(*) AS active_users FROM (
SELECT user_id, LASTWITHTIME(event_type, sequence_number, 'STRING') AS latest_ride_event
FROM operations WHERE {run_filter(simulation_id, as_of_ms)} AND user_id IS NOT NULL
AND event_type IN ({types(RIDE_TYPES)}) GROUP BY user_id)
WHERE latest_ride_event IN ('RIDE_REQUESTED','RIDE_ACCEPTED')"""


def observed_users(simulation_id: str, as_of_ms: int) -> str:
    return f"""SELECT COUNT(DISTINCT user_id) AS observed_users FROM operations
WHERE {run_filter(simulation_id, as_of_ms)} AND user_id IS NOT NULL"""


def event_rate(simulation_id: str, as_of_ms: int) -> str:
    return f"""SELECT DATETIMECONVERT(event_timestamp, '1:MILLISECONDS:EPOCH',
'1:MILLISECONDS:EPOCH', '10:SECONDS') AS time_bucket,
COUNT(*) AS event_count, COUNT(*) / 10.0 AS events_per_second FROM operations
WHERE {run_filter(simulation_id, as_of_ms)} AND event_timestamp >= {as_of_ms - 600_000}
GROUP BY time_bucket ORDER BY time_bucket ASC LIMIT 1000"""


def ingestion_metrics(simulation_id: str, as_of_ms: int) -> str:
    # One aggregate keeps the count and newest timestamp in the same query.
    return f"""SELECT COUNT(*) AS total_ingested_events,
MAX(event_timestamp) AS latest_event_timestamp FROM operations
WHERE {run_filter(simulation_id, as_of_ms)}"""
