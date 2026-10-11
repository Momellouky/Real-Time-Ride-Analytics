#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T kafka sh -ec '
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 \
    --create --if-not-exists --topic "$KAFKA_TOPIC" \
    --partitions 1 --replication-factor 1
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 \
    --describe --topic "$KAFKA_TOPIC"
'
