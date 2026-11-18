#!/usr/bin/env bash
set -euo pipefail

overall_status=0
passed_steps=0
total_steps=11
step_exit_code=0
worker_stopped=0
api_dev_enabled=0

run_step() {
  local name="$1"
  shift
  printf '\n=== %s ===\n' "$name"
  if "$@"; then
    step_exit_code=0
    passed_steps=$((passed_steps + 1))
    printf 'PASS: %s (exit code %s)\n' "$name" "$step_exit_code"
  else
    step_exit_code=$?
    overall_status=1
    printf 'FAIL: %s (exit code %s)\n' "$name" "$step_exit_code"
  fi
}

wait_for_health() {
  local attempt
  for ((attempt = 1; attempt <= 30; attempt++)); do
    if docker compose exec -T api python -c \
      'import sys, urllib.request; r=urllib.request.urlopen("http://localhost:8000/health", timeout=2); sys.exit(0 if r.status == 200 else 1)' \
      >/dev/null 2>&1; then
      printf 'HTTP 200 on attempt %s/30\n' "$attempt"
      return 0
    fi
    if (( attempt < 30 )); then
      sleep 2
    fi
  done
  printf 'Health check did not return HTTP 200 after 30 attempts.\n' >&2
  return 1
}

restart_worker() {
  if (( worker_stopped )); then
    run_step "Restart worker (cleanup)" docker compose start worker
    if (( step_exit_code == 0 )); then worker_stopped=0; fi
  fi
  if (( api_dev_enabled )); then
    run_step "Disable dev endpoint (cleanup)" env ENABLE_DEV_ENDPOINTS=false docker compose up -d --force-recreate api
    if (( step_exit_code == 0 )); then api_dev_enabled=0; fi
  fi
}
cleanup() {
  local exit_code=$?
  trap - EXIT
  restart_worker
  exit "$exit_code"
}
trap cleanup EXIT

run_step "Stop worker service" docker compose stop worker
if (( step_exit_code == 0 )); then worker_stopped=1; fi

run_step "API tests" docker compose exec api python -m pytest -q

run_step "Rejudge tests" docker compose exec api python -m pytest -q tests/test_rejudge.py

# Run the complete worker file with the service poller stopped so its race test
# is exercised only by the two worker processes started by that test.
run_step "Worker Docker tests" docker compose run --rm --no-deps worker python -m pytest -q tests/test_python_judge.py

run_step "Restart worker service" docker compose start worker
if (( step_exit_code == 0 )); then worker_stopped=0; fi

run_step "Seed standings check contest" docker compose exec api python -m scripts.seed_dev
run_step "Rebuild standings check" docker compose exec api python -m scripts.rebuild_standings

run_step "Enable dev endpoint for walkthrough" env ENABLE_DEV_ENDPOINTS=true docker compose up -d --force-recreate api
if (( step_exit_code == 0 )); then api_dev_enabled=1; fi

run_step "Wait for API health" wait_for_health

run_step "Swagger walkthrough" docker compose exec -e ENABLE_DEV_ENDPOINTS=true api python -m scripts.swagger_walkthrough

run_step "Restore API dev endpoint default" env ENABLE_DEV_ENDPOINTS=false docker compose up -d --force-recreate api
if (( step_exit_code == 0 )); then api_dev_enabled=0; fi

if (( overall_status == 0 )); then
  printf '\nSUMMARY: PASS (%s/%s steps; exit code 0)\n' "$passed_steps" "$total_steps"
else
  printf '\nSUMMARY: FAIL (%s/%s steps passed; exit code 1)\n' "$passed_steps" "$total_steps"
fi
exit "$overall_status"
