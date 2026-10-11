#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --create --if-not-exists \
  --topic ride-operations --partitions 1 --replication-factor 1
description=$(docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --describe --topic ride-operations)
printf '%s\n' "$description"
if [[ "$description" != *$'PartitionCount: 1\tReplicationFactor: 1'* ]]; then
  echo 'Existing ride-operations topic differs; expected one partition and one replica.' >&2
  exit 1
fi
