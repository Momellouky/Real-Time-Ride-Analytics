#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --wait --wait-timeout 240 \
  kafka pinot-zookeeper pinot-controller pinot-broker pinot-server
bash infra/kafka/create-topic.sh
bash infra/pinot/create-table.sh
bash infra/kafka/create-operations-topic.sh
python3 infra/pinot/provision_operations.py
docker compose --profile web up -d --build --wait --wait-timeout 120 frontend
docker compose --profile web ps
