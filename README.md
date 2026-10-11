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

The FastAPI service will validate submissions and expose current metrics and
history through an HTTP API. The Vue application will provide a metrics settings
page and a dashboard with five metric cards and charts, refreshed through polling.
Validation will require non-negative integers, accepted plus cancelled requests
no greater than total requests, and waiting drivers no greater than online drivers.

## Implementation status

The streaming infrastructure is implemented and verified: Kafka, Pinot Controller,
Broker, Server, schema registration, table registration, and an ingestion smoke
test. The test confirms snapshot integrity and rolling one-hour query behavior.

The FastAPI service and Vue interface are the next implementation phases.
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
├── backend/                       # Reserved for the FastAPI service
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

Infrastructure follows the [Pinot Docker documentation](https://docs.pinot.apache.org/start-here/install/docker)
and [Kafka 3.9 quick start](https://kafka.apache.org/39/getting-started/quickstart/).
