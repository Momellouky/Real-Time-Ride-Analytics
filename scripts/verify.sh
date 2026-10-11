#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s infra/pinot -p 'test_*.py'
bash scripts/setup-v2.sh
docker compose --profile web --profile test --profile e2e build \
  backend frontend frontend-test frontend-e2e
docker compose --profile web up -d --wait --wait-timeout 120 frontend
docker compose --profile api run --rm --no-deps backend python -m pytest -q
docker compose --profile api run --rm --no-deps backend python -m pip check
docker compose --profile test run --rm --no-deps frontend-test
python3 infra/pinot/smoke-test.py
docker compose exec -T backend python scripts/smoke-test.py
docker compose --profile web --profile e2e run --rm --no-deps frontend-e2e
docker compose exec -T backend python scripts/verify-operations-analytics.py
docker compose --profile web ps
