#!/usr/bin/env bash
set -Eeuo pipefail

worker_stopped=0
restart_worker() {
  if (( worker_stopped )); then
    docker compose start worker
    worker_stopped=0
  fi
}

docker compose exec api python -m pytest -q

docker compose stop worker
worker_stopped=1
trap restart_worker EXIT

# Run the complete worker file with the service poller stopped so its race test
# is exercised only by the two worker processes started by that test.
docker compose run --rm --no-deps worker python -m pytest -q tests/test_python_judge.py

docker compose start worker
worker_stopped=0
trap - EXIT
