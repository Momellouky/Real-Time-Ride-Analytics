# Real-Time Ride Analytics

Real-Time Ride Analytics is an operational analytics platform for monitoring
driver availability and ride request activity. It combines streaming ingestion
with analytical storage to provide current operational metrics and a historical
view of how those metrics evolve.

Each update captures a complete snapshot of five metrics:

| Metric | Description |
| --- | --- |
| Online drivers | Drivers currently online. |
| Ride requests | Total ride requests represented by the snapshot. |
| Accepted requests | Ride requests that have been accepted. |
| Cancelled requests | Ride requests that have been cancelled. |
| Waiting drivers | Online drivers waiting in the configured zone. |

Snapshots are immutable: new updates append to the history rather than overwrite
previous values. The newest snapshot represents current state, while timestamped
observations support time-series analysis. Every snapshot carries an event ID,
a UTC timestamp in epoch milliseconds, and a zone identifier.

## Architecture

The application architecture separates metric submission from analytical reads:

```text
Vue Settings → FastAPI validation → Kafka → Apache Pinot REALTIME table
Vue Dashboard ← FastAPI analytics API ← Apache Pinot Broker
```

Kafka transports complete snapshots through the `ride-metrics-snapshots` topic.
Apache Pinot consumes those events directly into `ride_metrics_REALTIME` and
serves SQL queries for the latest snapshot and rolling one-hour history.
ZooKeeper coordinates the Pinot cluster; Kafka runs independently in KRaft mode.

The FastAPI service validates complete snapshot submissions, publishes them to
Kafka, and exposes current metrics and history through an HTTP API.
The Vue application provides a metrics settings page for editing and publishing
complete snapshots, plus a dashboard with five metric cards and rolling one-hour
charts refreshed through polling.
Validation requires non-negative integers, accepted plus cancelled requests
no greater than total requests, and waiting drivers no greater than online drivers.

## Quick start

Requirements: Docker with Compose v2 or newer, Bash, and Python 3.10 or newer.
Allow roughly 4 GB of available memory plus disk space for images and data.
Node.js and Python package tooling on the host are optional; Docker builds both
applications.

```bash
bash scripts/start.sh
```

This starts Kafka and Pinot, creates or checks their resources, builds both
applications, and waits for service health checks. Repeating the command preserves
stored snapshots. Existing Pinot resources are checked for compatible schema and
ingestion configuration; conflicting resources produce an error for review.
Startup does not insert sample data.

- Dashboard: http://localhost:5173
- Metrics Settings: http://localhost:5173/settings
- Event Generator: http://localhost:5173/generator
- API documentation: http://localhost:8000/docs
- Pinot Controller and Query Console: http://localhost:9000

To customize configuration, copy `.env.example` to `.env` before starting.
Environment variables take precedence over that file.

Stop the applications and infrastructure while retaining stored data:

```bash
docker compose --profile web down
```

Start again with `bash scripts/start.sh`.

## Implementation status

The streaming infrastructure is implemented and verified: Kafka, Pinot Controller,
Broker, Server, schema registration, table registration, and an ingestion smoke
test. The test confirms snapshot integrity and rolling one-hour query behavior.

The FastAPI read service provides current snapshots, one-hour history, structured
response validation, and explicit errors when Pinot is unavailable or returns
incomplete results. Automated tests cover the query client and HTTP endpoints.
The write service validates complete snapshots, generates event metadata, and
publishes acknowledged events through a reusable asynchronous Kafka producer.
The Vue Settings page loads current values, preserves unchanged metrics, validates
inputs, and submits complete snapshots with loading, success, and error feedback.
The dashboard provides current values and five Chart.js time-series charts through
a combined API response. Polling refreshes the dashboard automatically and retains
the last successful data during query failures.
The implementation covers the PRD's single-zone snapshot workflow. The current
configuration supports one zone (`ZONE_1`), with one Kafka partition
and one Pinot replica.

## v2 event-driven pipeline

The v2 implementation adds immutable ride and driver events alongside the existing
v1 snapshot workflow. Its data plane, simulation model, scheduler, lifecycle, and
Generator API/UI controls, Pinot analytical queries, and combined dashboard API/UI
are available now. Standard startup provisions both workflows;
the independent v2 setup command below is also available.
The v1 Settings page, APIs, topic, table, and dashboard retain their behavior.

```text
Ride/driver events → Kafka ride-operations → Pinot operations_REALTIME
```

Provision the v2 data plane independently:

```bash
bash scripts/setup-v2.sh
python3 infra/pinot/smoke_test_operations.py
```

Setup starts or reuses the shared infrastructure and creates a separate topic with
one partition and one replica. It registers the `operations` schema and REALTIME
table, or checks existing resources for compatibility. It does not overwrite
existing configurations or insert test data. Provision v1 with `scripts/start.sh`
when starting both workflows from an empty cluster.

The smoke test adds ten events under a unique `smoke-...` simulation ID. It covers
all eight event types using a driver connection, a cancelled request, an accepted
and completed ride, and a driver disconnection. It verifies every stored field,
null entity IDs, exact per-type counts, and sequence ordering. Repeated checks
append another independent run; old events remain available for inspection.

The event envelope carries event ID/version, simulation ID, sequence number,
timestamp, event type, zone, and nullable user/driver/ride IDs. The single zone is
`ZONE_1`. Every v2 dashboard query filters on its simulation ID.
Column-based null handling preserves absent entity IDs. Time range and
simulation/type/zone indexes support analytical filtering. Segment flush settings
use a one-hour interval and a 100 MB target size.

The committed configuration uses `ingestionConfig.streamIngestionConfig`, as in
the [Pinot stream ingestion guide](https://docs.pinot.apache.org/build-with-pinot/ingestion/stream-ingestion/stream-ingestion),
instead of the plan's legacy `tableIndexConfig.streamConfigs` placement.

Inspect a run in the Controller query console:

```sql
SET enableNullHandling=true;
SELECT * FROM operations
WHERE simulation_id = 'SMOKE_SIMULATION_ID'
ORDER BY sequence_number ASC
LIMIT 100;

SELECT event_type, COUNT(*) FROM operations
WHERE simulation_id = 'SMOKE_SIMULATION_ID'
GROUP BY event_type;
```

If ingestion stalls, inspect Kafka's `ride-operations` topic and the Controller's
`operations_REALTIME` consuming segments, then check Pinot server logs. The v2
smoke test rejects Broker SQL errors and incomplete server responses. Setup
rejects conflicting schemas, ingestion settings, or topic partition/replica counts
so existing analytical data remains intact.

Phase 1 results are recorded in [docs/v2-step-1-verification.md](docs/v2-step-1-verification.md).

### Simulation model

`backend/app/generator/` provides users, drivers, active rides, immutable operation
events, and six business actions: connect/disconnect a driver and
request/cancel/accept/complete a ride. A fresh simulation initializes users as IDLE
and drivers as OFFLINE, with a unique simulation ID and sequence starting at zero.
Invalid actions return no events and leave domain state unchanged.

State pools use dense arrays with position indexes for constant-time selection,
insertion, and removal. Selection excludes unavailable actions and can filter by
event budget; action costs distinguish one-event actions from two-event actions.
Weights match the v2 plan. The scheduler consumes this interface without
scanning the entire population on each tick.

Each successful action returns immutable events ready for JSON serialization.
Sequences increase per event, including paired transitions. Timestamps do not
regress if the wall clock moves backward. Completed/cancelled rides are removed
from active memory; their returned events carry history for later publication.
Memory therefore depends on pool sizes rather than the lifetime event count.

`Simulation.counts()` supplies generator diagnostics; `check_invariants()` audits
state indexes and reciprocal user/driver/ride relationships for tests and
debugging. These diagnostics do not replace Pinot dashboard analytics.
The model has no Kafka side effects or background tasks and expects one owner
to execute actions sequentially. The generator service described below owns
execution and Kafka publication.

Run the simulation and existing backend tests without starting the application:

```bash
docker compose --profile api build backend
docker compose --profile api run --rm --no-deps backend python -m pytest -q
```

Phase 2 results are recorded in [docs/v2-step-2-verification.md](docs/v2-step-2-verification.md).

### Scheduler and generator lifecycle

`GeneratorService` is attached to FastAPI application state, initially STOPPED.
It opens its separate operations producer only when started; loading the API
does not generate events or require the v2 topic. One API process owns one generator; multiple workers
would each have independent state and are outside this setup.

Start validates pool sizes and a positive integer event rate, creates a fresh
simulation and immutable run metadata, and enters WARMING_UP. It connects 10% of
drivers (rounded up, at least one) through normal connected/waiting events before
entering RUNNING. Start during WARMING_UP, RUNNING, or STOPPING raises a conflict.

The scheduler issues event budgets every 100 ms, accounting for both one-event
and two-event actions. Integer tenths preserve fractional credits. Budget is
bounded to avoid catch-up bursts; one batch is generated/published at a time, so
slow Kafka delivery reduces measured throughput rather than growing a queue.

The dedicated producer targets `ride-operations` partition 0 with JSON events,
`acks=all`, idempotence, and 5 ms linger. It enqueues a tick's events in sequence,
then awaits all delivery acknowledgements, following the
[aiokafka producer batching model](https://aiokafka.readthedocs.io/en/latest/producer.html).
Idempotence protects transport retries; batches are not Kafka transactions, so
paired transitions can briefly be observed separately during ingestion.

Stop signals scheduling to halt, finishes the current batch, and drains Kafka
sends before marking STOPPED. Repeated Stop is safe. Final statistics remain
visible until the next Start creates a fresh run. Application shutdown stops the
generator before closing the v1 producer and Pinot client.

Status separates `generated_events` from Kafka-acknowledged `published_events`.
`actual_events_per_second` measures acknowledged events over a rolling interval
of approximately five seconds; final rate/statistics are retained after stopping.
Pinot ingestion throughput will be measured separately in the analytics phase.
Summary logs appear every five seconds and at run completion.

Publication or drain failure ends the run in ERROR with `last_error`. The service
does not replay a batch whose delivery is uncertain. Some records may have been
delivered before failure, and in-memory diagnostics can then differ from Pinot;
restart creates a fresh simulation ID. The configured Kafka timeout bounds
startup, batch publication, and drain independently. A timed-out drain reports
ERROR rather than claiming graceful completion.

Verify the complete backend suite with the commands above. For a finite live
check, provision v2 and run:

```bash
bash scripts/setup-v2.sh
docker compose --profile api build backend
docker compose --profile api run --rm --no-deps backend python scripts/verify-generator.py
```

This adds about 3,000 v2 events across two independent runs (10 seconds and
2 seconds at 250 events/sec). It checks graceful stopping, fresh restart, exact
Pinot row counts, event IDs/sequences, all event types, and reconstruction of
current state after ingestion settles. Existing v1 snapshots are not modified.
Phase 3 results are recorded in [docs/v2-step-3-verification.md](docs/v2-step-3-verification.md).

### Generator controls

Open [the Generator page](http://localhost:5173/generator) from the main
navigation. Configure the user and driver pools (defaults 10,000 and 2,000),
choose 50/100/250/500/1,000 events per second or a custom positive integer, and
select **Start Generator**. Custom rates above 1,000 events/sec show a resource
warning but remain selectable. The zone is fixed to `ZONE_1`.

The page refreshes status every second and displays simulation ID, target/actual
publication rate, generated/published events, configured pools, and six population
diagnostics. Start/configuration are disabled during active runs; Stop waits for
the current batch and Kafka drain. Stopped or failed runs retain their statistics.
Reloading the page reconnects to the current run. Leaving the page stops status
polling but keeps the generator running until Stop or application shutdown.

| Method | Endpoint | Result |
| --- | --- | --- |
| POST | `/api/v2/generator/start` | 202 with fresh run status; 409 if already active, 422 for invalid configuration, 503 if producer startup fails. |
| POST | `/api/v2/generator/stop` | 200 with final status; inspect `status` and `last_error` because drain failures return ERROR. Repeated Stop is safe. |
| GET | `/api/v2/generator/status` | Typed runtime status and diagnostics, including initial zero values before the first run. |

Start requires all three positive integer settings and rejects unknown fields:

```bash
curl -sS -X POST http://localhost:8000/api/v2/generator/start \
  -H 'Content-Type: application/json' \
  -d '{"user_count":10000,"driver_count":2000,"target_events_per_second":250}'
curl -sS http://localhost:8000/api/v2/generator/status
curl -sS -X POST http://localhost:8000/api/v2/generator/stop
```

Status failures retain the last diagnostics and offer retry. A failed control
request triggers a status refresh before another Start; it can have succeeded
on the server even when the browser did not receive a response. Older polling
responses cannot overwrite a newer control result. No transactional database is
used; process restart clears runtime state while stored events remain.

Run Generator browser checks against a stopped generator:

```bash
docker compose --profile web --profile e2e build frontend-e2e
docker compose --profile web --profile e2e run --rm --no-deps frontend-e2e \
  npm run test:e2e -- generator.spec.js
```

The live test creates two finite runs at 50 events/sec and verifies their exact
Pinot row counts. Other Generator browser scenarios use intercepted responses.
Phase 4 results are recorded in [docs/v2-step-4-verification.md](docs/v2-step-4-verification.md).

### Pinot analytical queries

`backend/app/queries/operations.py` defines the v2 SQL, and
`OperationsAnalytics` executes six queries concurrently and parses typed results.
It accepts a simulation ID and captures one epoch-millisecond cutoff for the
whole read. Queries filter that run, `ZONE_1`, and events at or before the cutoff.
Different queries can briefly observe different ingestion progress; this is not
a transactional snapshot.

| Result | Definition |
| --- | --- |
| Recent ride activity | Requested/accepted/cancelled/completed event counts over the last 60 seconds. |
| Latest driver state | Latest driver event over the whole run; waiting, assigned, connected, disconnected, online, and observed counts. |
| Active users | Users whose latest ride event is requested or accepted, over the whole run. |
| Observed users | Exact distinct non-null user IDs observed in the run. |
| Ride history | Four lifecycle counts per minute over the last hour. |
| Ingested event rate | All ingested event counts divided by 10 per 10-second bucket over the last ten minutes. |

Current-state queries have no lower time bound: an accepted ride or assigned
driver does not disappear simply because its last transition is over an hour
old. Missing ride categories are zero; empty runs return zero counts and empty
time series. Time series contain observed buckets only. The first/last buckets
can be partial, and their rate still uses the fixed ten-second denominator.
This is ingestion-visible event-time throughput, distinct from the generator's
rolling publication rate.

The installed Pinot 1.5.1 rejected the plan's `ARG_MAX(timestamp, sequence, type)`
signature. Latest-state queries use
[`LASTWITHTIME`](https://docs.pinot.apache.org/release-1.1.0/configuration-reference/functions/lastwithtime)
on `sequence_number`. The generator guarantees increasing per-run sequences and
non-regressing timestamps, so this resolves timestamp ties and preserves the
intended state ordering. Imported events must honor that contract; arbitrary
sequences with regressing timestamps do not represent valid simulation runs.

The service enables `useMultistageEngine=true` and `enableNullHandling=true`
per query. Both worked on the running cluster without infrastructure changes.
v1 queries retain their original request options. Broker errors, partial results,
missing server responses, group trimming, and join/window limit truncation are
errors rather than zero metrics. SQL builders validate run IDs before interpolation.

Driver `disconnected` counts only drivers observed to disconnect. Drivers that
never connected have no event; phase 6 derives the complete offline population
from immutable driver-pool metadata minus Pinot-derived online drivers.

Verify known event sequences against real Pinot:

```bash
docker compose --profile api build backend
docker compose --profile api run --rm --no-deps backend python -m pytest -q
docker compose --profile api run --rm --no-deps backend python scripts/verify-operations-analytics.py
```

The live script appends 21 events across two unique fixture runs. It checks null
IDs, timestamp ties, old active state, future exclusion, time buckets, isolation,
empty runs, and reconciliation with the application's stopped simulation when
available. It never writes v1 snapshots or changes the application's generator.
Phase 5 results are recorded in [docs/v2-step-5-verification.md](docs/v2-step-5-verification.md).

## Repository structure

```text
.
├── docker-compose.yml             # Streaming and analytical services
├── .env.example                   # Configuration defaults
├── scripts/                       # Full startup and verification commands
├── docs/verification.md           # Acceptance coverage and verification results
├── infra/
│   ├── kafka/create-topic.sh       # Kafka topic provisioning
│   └── pinot/
│       ├── server.conf            # Persistent segment storage paths
│       ├── ride-metrics-schema.json
│       ├── ride-metrics-realtime-table.json
│       ├── create-table.sh        # Schema and table registration
│       ├── sample-event.json      # Complete snapshot template
│       └── smoke-test.py          # Kafka → Pinot ingestion verification
├── backend/                       # FastAPI service, Dockerfile, and tests
└── frontend/                      # Vue application, API client, store, and tests
```

## Start the infrastructure

Requirements: Docker with Compose v2 or newer, Bash, and Python 3.10 or newer.
Allow roughly 4 GB of available memory plus disk space for images and data.

From this directory:

```bash
docker compose up -d --wait --wait-timeout 240
bash infra/kafka/create-topic.sh
bash infra/pinot/create-table.sh
python3 infra/pinot/smoke-test.py
```

The smoke test publishes one snapshot with a new UUID and current UTC epoch
milliseconds, waits up to two minutes for ingestion, and checks every field,
the single matching row, and the rolling one-hour filter. Each run adds a row.
The sample JSON is a template; its fixed timestamp is replaced by the smoke test.

Open the Controller and Query Console at http://localhost:9000. Run:

```sql
SELECT * FROM ride_metrics ORDER BY event_timestamp DESC LIMIT 10;
SELECT COUNT(*) FROM ride_metrics;
SELECT * FROM ride_metrics
WHERE zone_id = 'ZONE_1' AND event_timestamp >= ago('PT1H')
ORDER BY event_timestamp ASC LIMIT 5000;
```

The Broker API is available at http://localhost:8099/query/sql:

```bash
curl -fsS http://localhost:8099/query/sql \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT * FROM ride_metrics ORDER BY event_timestamp DESC LIMIT 1"}'
```

## Configuration and persistence

Compose reads `.env`; defaults also work without it. Kafka has separate internal
(`kafka:9092`) and host (`localhost:9092`) listeners. Pinot uses the internal
listener. ZooKeeper coordinates Pinot; Kafka uses KRaft and needs no ZooKeeper.
The topic has one partition and one replica. The table has one replica, no upsert,
a zone inverted index, and a timestamp range index.

`KAFKA_TOPIC` is used by topic creation, table registration, and the smoke test.
If changing it, do so before creating the table. The committed JSON defines the
default topic; registration renders the chosen topic into a temporary container
file. `ZONE_ID` is fixed to `ZONE_1` in this version; changing it does not enable
other zones. Host ports and image versions are
configurable. If changing ports, also update the corresponding host URLs and
bootstrap address for host backend development.

Named volumes retain Kafka logs, ZooKeeper state, and Pinot segments across
container recreation. Stop with `docker compose down`; start again with the same
`up` command. Topic creation can be repeated. Table registration uses Pinot's
AddTable command only for missing resources. Matching resources are reused;
changes to an existing table should be made deliberately via the Controller API
rather than by recreating resources.

The backend Docker build installs exact runtime and test versions from
`backend/requirements.lock`. Frontend builds use `npm ci` with
`frontend/package-lock.json`. Dependency updates should refresh the corresponding
lockfile and pass the verification suite.

## Start the analytics API

With the infrastructure running and the Pinot table registered:

```bash
docker compose --profile api up -d --build --wait backend
```

The `api` profile adds FastAPI to the existing stack. Its Broker connection uses
`http://pinot-broker:8099` inside Docker. `BACKEND_PORT` (default `8000`) controls
the host port; `PINOT_QUERY_TIMEOUT_SECONDS` (default `3`) controls query timeouts.
Interactive API documentation is available at http://localhost:8000/docs.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | `/api/metrics` | Validate and publish a complete snapshot; return `202` after Kafka acknowledgement. |
| GET | `/health` | Process health; does not check Pinot availability. |
| GET | `/api/metrics/current?zone_id=ZONE_1` | Latest stored snapshot, regardless of its age. |
| GET | `/api/metrics/history?zone_id=ZONE_1&window=1h` | Snapshot observations from the previous hour, ordered by timestamp. |
| GET | `/api/dashboard?zone_id=ZONE_1&window=1h` | Combined `{current, history}` response, with both Pinot queries executed concurrently. |

Zone and window parameters default to `ZONE_1` and `1h`. Unsupported values
return HTTP `422`. History returns a JSON array containing the timestamp and all
five metric values per observation, with a maximum of 5,000 points. Future-dated
observations are excluded from history. Current metrics include event metadata;
an empty table returns five zeros, `zone_id: "ZONE_1"`, and null `event_id` and
`event_timestamp`. Empty history returns `[]`.

Pinot transport failures, SQL exceptions, partial results, and malformed results
return HTTP `503` with a readable error. Such failures do not become zero state.

```bash
curl -fsS http://localhost:8000/health
curl -fsS 'http://localhost:8000/api/metrics/current?zone_id=ZONE_1'
curl -fsS 'http://localhost:8000/api/metrics/history?zone_id=ZONE_1&window=1h'
docker compose --profile api run --rm --no-deps backend python -m pytest -q
```

For host development, use Python 3.11 or newer with pip and venv support:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock
backend/.venv/bin/python -m pip install --no-deps -e backend
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload
backend/.venv/bin/python -m pytest backend/tests -q
```

Host development reads the root `.env` file and uses `PINOT_BROKER_URL`.
The API reuses one asynchronous HTTP client, opened at startup and closed at
shutdown, and one Kafka producer managed through the same lifecycle. Kafka must
be reachable at startup. A startup failure closes both clients and prevents the
application from serving requests.

## Submit metric snapshots

Send the zone and all five metrics with every submission:

```bash
curl -i http://localhost:8000/api/metrics \
  -H 'Content-Type: application/json' \
  -d '{"zone_id":"ZONE_1","online_drivers":75,"ride_requests":100,"accepted_requests":60,"cancelled_requests":15,"waiting_drivers":20}'
```

A successful response has this structure:

```json
{
  "status": "accepted",
  "event_id": "backend-generated-uuid",
  "event_timestamp": 1791707400000
}
```

`202` confirms Kafka acknowledgement. Pinot ingestion is asynchronous; use the
current and history endpoints to observe the snapshot after ingestion.
The backend generates UUID event IDs and UTC epoch-millisecond timestamps.
It does not query Pinot to fill missing values.

Requests must contain only the zone and five metric fields. Metrics must be JSON
integers between `0` and `2147483647`, matching Pinot's `INT` storage. Nulls,
booleans, strings, missing fields, and client-supplied event metadata are rejected.
Accepted plus cancelled requests must not exceed ride requests; waiting drivers
must not exceed online drivers. Pending requests are allowed. Invalid submissions
return `422` and publish no event.

The producer uses `acks=all` and idempotent delivery. Publication errors or an
unconfirmed acknowledgement return `503`. `KAFKA_PUBLISH_TIMEOUT_SECONDS`
(default `10`) bounds startup and publication waits. An acknowledgement timeout
can leave delivery uncertain; a separate HTTP submission creates a new event,
so producer idempotence does not deduplicate repeated HTTP requests.

Host development uses `KAFKA_BOOTSTRAP_SERVERS` from `.env`; the container uses
`kafka:9092`. Both use `KAFKA_TOPIC`. Create the topic and register the corresponding
Pinot table before submitting snapshots.

Run the complete write-path check against the running backend:

```bash
docker compose exec -T backend python scripts/smoke-test.py
```

This adds one valid snapshot, verifies invalid requests emit no Kafka events,
checks the complete Kafka event, and waits for exactly one matching Pinot row
and matching current/history responses.

## Metrics Settings

Start the frontend and backend with the existing Kafka and Pinot stack:

```bash
docker compose --profile web up -d --build --wait frontend
```

Open http://localhost:5173/settings. The home page at http://localhost:5173
provides the Analytics Dashboard. `FRONTEND_PORT` controls the published frontend port.
The web container serves the built application through Nginx and proxies `/api`
requests to FastAPI, keeping browser traffic on the same origin.

The form loads the latest Pinot-backed snapshot before enabling editing. An empty
table initializes all five values to zero. Loading failures disable the form and
offer a retry so unavailable data is never mistaken for an empty table. Editing
one field preserves the other values in Pinia state.

Inputs enforce the same integer limits and business rules as the API. Publishing
sends `zone_id` and all five metric values, disables editing while the request is
pending, and displays acknowledgement or error feedback. Failed submissions
preserve edits. A successful submission confirms acceptance; reloading Settings
retrieves the latest values once Pinot ingestion completes.

Run the frontend tests:

```bash
docker compose --profile test run --build --rm --no-deps frontend-test
docker compose --profile web --profile e2e run --build --rm frontend-e2e
```

Unit tests cover validation, initialization, complete submissions, API errors,
duplicate-submit prevention, and dashboard polling. Chromium browser tests cover
retry behavior, validation, publishing errors, responsive layout, and the complete
Settings → API → Kafka → Pinot → Dashboard flow. The two live browser tests each
add one snapshot by incrementing online drivers: one verifies Settings reloads
persisted values, and the other verifies Dashboard updates without a reload.
Screenshots and failure traces are written under
`frontend/test-results/`.

For frontend development on a host with Node.js 22.12 or newer:

```bash
cd frontend
npm ci
npm run dev
npm test
npm run build
```

Vite reads the root `.env` file. Its `/api` proxy uses `VITE_API_PROXY_TARGET`
(default `http://localhost:8000`); update this if changing the backend host port.

## Analytics Dashboard

Open http://localhost:5173 to see the latest values and one-hour history for all
five metrics. Each card shows its current value and a chart of raw observations,
with actual elapsed time on the horizontal axis. Lines connect submitted points
without smoothing or fabricated samples. A single observation remains visible as
a point. Chart tooltips and axis labels display timestamps in the browser's local
time zone.

The dashboard fetches `/api/dashboard` immediately and polls every two seconds.
`DASHBOARD_POLL_INTERVAL_MS` configures this interval (`250`–`2147483647`; invalid
values fall back to `2000`). For Docker, change `.env` and rebuild the frontend:

```bash
docker compose --profile web up -d --build --wait frontend
curl -fsS 'http://localhost:8000/api/dashboard?zone_id=ZONE_1&window=1h'
```

Vite host development reads the same setting from the root `.env`; restart the
development server after changing it. Only one dashboard request can be in flight
at a time. Leaving the dashboard clears its timer, aborts pending requests, and
destroys its charts. Dashboard state is separate from editable Settings state.

Empty tables show zero values and guidance to publish the first snapshot. Empty
history shows an explicit chart empty state, even when a current snapshot exists
outside the last-hour window. Refresh errors retain the previous values and
charts, show the time of the last successful update, and offer an immediate retry
while automatic polling continues. Initial failures display a retry without
inventing zero-valued metrics.

Current and history queries execute concurrently rather than as a transactional
read; asynchronous ingestion can briefly appear in one query before the other.
The following poll retrieves the updated state. History retains the existing
5,000-point query limit.

## Complete verification

After startup, run all provisioning, backend, frontend, ingestion, and browser checks:

```bash
bash scripts/verify.sh
```

The runner provisions v2 resources, builds the current code, starts the web application, runs the automated
tests and dependency consistency check, verifies a manually published Kafka event,
verifies an API submission, and runs Chromium tests. It stops at the first failure.
Run verification while the generator is stopped. The live checks add four v1
snapshots to the selected stack: one manual event, one
API submission, and two Settings submissions. Each browser submission increments
online drivers and preserves the other four values. Generator browser checks
also append two finite v2 runs; event counts depend on test duration. Analytical
verification adds another 21 isolated v2 fixture events. Use a separate Compose project
and alternate ports when verifying without modifying existing analytical data.

Acceptance coverage, clean-start and restart checks, and history-boundary results
are recorded in [docs/verification.md](docs/verification.md).

`/health` reports API process health. Compose also checks the Kafka broker,
ZooKeeper, Pinot Controller, Broker, Server, and web server independently. Use the
metrics endpoints to check analytical availability; `/health` alone does not prove
that ingestion and queries are working.

## Troubleshooting

```bash
docker compose ps
docker compose logs --tail=100 kafka pinot-controller pinot-broker pinot-server
docker compose exec kafka sh -c \
  '/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic "$KAFKA_TOPIC" --from-beginning'
```

If Kafka contains events but Pinot does not, inspect `ride_metrics_REALTIME` in
the Controller UI: check consuming segments, topic name, and server logs. Pinot
must connect to `kafka:9092`. Broker responses may contain SQL exceptions even
with HTTP 200; the smoke test checks those explicitly.

If a host port is occupied, change its value in `.env`. If Docker reports
permission denied, ensure your user has access to the Docker daemon.

If startup reports conflicting Pinot resources, inspect the Controller schema and
table configuration against the files in `infra/pinot/`. Setup will not overwrite
existing resources to resolve a mismatch. Confirm `KAFKA_TOPIC` has not changed.

For API errors, inspect `docker compose logs --tail=100 backend`. A successful
`/health` response establishes process health only. Check the Broker and Server
when metrics endpoints return `503`. A stored snapshot older than one hour can
appear in current metrics while history is empty.

For frontend connectivity errors, inspect
`docker compose logs --tail=100 frontend backend`. Confirm the backend is healthy and `/api/metrics/current` responds
through the frontend address. Direct navigation to `/settings` is supported by
the web server's application fallback.

Infrastructure follows the [Pinot Docker documentation](https://docs.pinot.apache.org/start-here/install/docker)
and [Kafka 3.9 quick start](https://kafka.apache.org/39/getting-started/quickstart/).

## Event Analytics Dashboard (v2)

Open http://localhost:5173/dashboard-v2, or choose **Event Dashboard** in the
navigation. Start and stop runs from **Generator**. The dashboard polls
`GET /api/v2/dashboard` every two seconds, using the same configurable polling
interval as the snapshot dashboard.

The eight cards show the configured user population, active users, online and
waiting drivers, and requested, accepted, cancelled, and completed rides in the
last 60 seconds. Active users have a latest ride state of requested or accepted;
online drivers have a latest driver state of connected, waiting, or assigned.
Population comes from immutable run metadata; activity and fleet state come from
Pinot. Generator diagnostics and Kafka acknowledgement rates are not substituted
for analytics.

The charts show four ride lifecycle series per minute over the last hour,
Pinot-ingested events per second in 10-second buckets over the last 10 minutes,
and current driver distribution. Each rate bucket divides its ingested event
count by ten; the open bucket is partial. The distribution includes connected,
waiting, assigned, and offline drivers. Offline includes drivers that have never
connected, so its total always matches the configured driver pool.

The combined response contains `run`, `generator_status`, `generator_error`,
`as_of_ms`, `metrics`, `driver_states`, `observed_users`, `ride_history`, and
`event_rate`. All six analytical queries share one run ID and timestamp cutoff.
Before the first run it returns null run metadata, zero cards, and empty series
without querying Pinot. A stopped run retains metadata and latest entity state;
its activity windows continue to expire. Starting another run replaces all cards
and series. Restarting the backend clears its process-owned run metadata; old
events remain in Pinot but are excluded from subsequent runs.

A run changing while queries execute produces HTTP `409` and is retried by the
next poll. Unavailable or invalid analytics produce HTTP `503`. During failures
the UI labels and retains the last successful response, offers a retry button,
and recovers automatically. Polling never overlaps requests and is cancelled
when leaving the page.

```bash
curl -fsS http://localhost:8000/api/v2/dashboard
```

Browser verification also starts two v2 runs, verifies ingestion and stopped-run
state against generator diagnostics, and checks that the second run replaces the
first. These tests append operations events; they do not publish v1 snapshots.
Step 6 verification results are recorded in
[docs/v2-step-6-verification.md](docs/v2-step-6-verification.md).
