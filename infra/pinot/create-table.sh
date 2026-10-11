#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# Render a temporary table config using Compose's resolved topic configuration.
topic=$(docker compose exec -T kafka printenv KAFKA_TOPIC)
python3 - "$topic" <<'PY' | docker compose exec -T pinot-controller sh -c 'cat > /tmp/ride-metrics-realtime-table.json'
import json
import sys
from pathlib import Path
table = json.loads(Path('infra/pinot/ride-metrics-realtime-table.json').read_text())
table['ingestionConfig']['streamIngestionConfig']['streamConfigMaps'][0]['stream.kafka.topic.name'] = sys.argv[1]
print(json.dumps(table))
PY
docker compose exec -T pinot-controller /opt/pinot/bin/pinot-admin.sh AddTable \
  -schemaFile /config/ride-metrics-schema.json \
  -tableConfigFile /tmp/ride-metrics-realtime-table.json \
  -controllerHost pinot-controller -controllerPort 9000 -exec
