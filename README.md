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
The Vue application will provide a metrics settings
page and a dashboard with five metric cards and charts, refreshed through polling.
Validation requires non-negative integers, accepted plus cancelled requests
no greater than total requests, and waiting drivers no greater than online drivers.

## Implementation status

The streaming infrastructure is implemented and verified: Kafka, Pinot Controller,
Broker, Server, schema registration, table registration, and an ingestion smoke
test. The test confirms snapshot integrity and rolling one-hour query behavior.

The FastAPI read service provides current snapshots, one-hour history, structured
response validation, and explicit errors when Pinot is unavailable or returns
incomplete results. Automated tests cover the query client and HTTP endpoints.
The write service validates complete snapshots, generates event metadata, and
publishes acknowledged events through a reusable asynchronous Kafka producer.
The Vue settings page and dashboard are the next implementation phases.
The current configuration supports one zone (`ZONE_1`), with one Kafka partition
and one Pinot replica.

## Repository structure

```text
.
├── docker-compose.yml             # Streaming and analytical services
├── .env.example                   # Configuration defaults
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
└── frontend/                      # Reserved for the Vue application
```

## Start the infrastructure

Requirements: Docker with Compose v2 or newer, Bash, and Python 3.10 or newer.
Allow roughly 4 GB of available memory plus disk space for images and data.

From this directory:

```bash
cp .env.example .env
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
file. `ZONE_ID` remains `ZONE_1` for this phase. Host ports and image versions are
configurable. If changing ports, also update the corresponding host URLs and
bootstrap address for future backend use.

Named volumes retain Kafka logs, ZooKeeper state, and Pinot segments across
container recreation. Stop with `docker compose down`; start again with the same
`up` command. Topic creation can be repeated. Table registration uses Pinot's
AddTable command; changes to an existing table should be made deliberately via
the Controller API rather than by recreating resources.

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
backend/.venv/bin/python -m pip install -e './backend[test]'
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

For API errors, inspect `docker compose logs --tail=100 backend`. A successful
`/health` response establishes process health only. Check the Broker and Server
when metrics endpoints return `503`. A stored snapshot older than one hour can
appear in current metrics while history is empty.

Infrastructure follows the [Pinot Docker documentation](https://docs.pinot.apache.org/start-here/install/docker)
and [Kafka 3.9 quick start](https://kafka.apache.org/39/getting-started/quickstart/).
