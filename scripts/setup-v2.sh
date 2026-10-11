#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --wait --wait-timeout 240 \
  kafka pinot-zookeeper pinot-controller pinot-broker pinot-server
bash infra/kafka/create-operations-topic.sh
python3 infra/pinot/provision_operations.py
