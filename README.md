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
v1 snapshot workflow. Its data plane is available now; the simulation engine,
generator controls, analytical APIs, and v2 dashboard follow in later phases.
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
`ZONE_1`. Every future v2 dashboard query must filter on its simulation ID.
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

The runner builds the current code, starts the web application, runs the automated
tests and dependency consistency check, verifies a manually published Kafka event,
verifies an API submission, and runs Chromium tests. It stops at the first failure.
The live checks add four snapshots to the selected stack: one manual event, one
API submission, and two Settings submissions. Each browser submission increments
online drivers and preserves the other four values. Use a separate Compose project
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
