"""Exercise POST submissions with ten concurrent HTTP clients for 30 seconds."""
from __future__ import annotations

import os
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contest, ContestParticipant, ContestProblem, Problem, User
from scripts.seed_dev import DEMO_PASSWORD, PROBLEMS

CLIENTS = 10
DURATION_SECONDS = 30
BASE_URL = os.getenv("EASECODING_API_URL", "http://localhost:8000/api/v1").rstrip("/")
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "load_test.txt"


def percentile(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> int:
    with SessionLocal() as db:
        contest = db.scalar(
            select(Contest).where(Contest.title == "Easecoding Demo Contest A").order_by(Contest.id.desc()).limit(1)
        )
        if not contest:
            print("ERROR: demo contest not found; run python -m scripts.seed_dev first")
            return 1
        problem = db.scalar(select(Problem).where(
            Problem.organization_id == contest.organization_id,
            Problem.title == "Two Number Sum",
        ))
        pin = db.scalar(select(ContestProblem).where(
            ContestProblem.contest_id == contest.id,
            ContestProblem.problem_id == problem.id if problem else False,
        ))
        participant = db.scalar(select(User).where(User.email == "participant@example.test"))
        registration = db.scalar(select(ContestParticipant).where(
            ContestParticipant.contest_id == contest.id,
            ContestParticipant.user_id == participant.id if participant else False,
        ))
        if not problem or not pin or not participant or not registration or registration.status != "registered":
            print("ERROR: seeded participant, contest and Two Number Sum pin are required")
            return 1
        contest_id, pin_id = contest.id, pin.id

    with httpx.Client(timeout=15.0) as client:
        login = client.post(f"{BASE_URL}/auth/login", json={
            "email": "participant@example.test", "password": DEMO_PASSWORD,
        })
        login.raise_for_status()
        token = login.json()["access_token"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"load-test-{uuid4().hex}",
    }
    body = {"source_code": PROBLEMS["Two Number Sum"]["program"], "language": "python"}
    deadline = time.monotonic() + DURATION_SECONDS
    latencies_ms: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()

    def client_loop():
        with httpx.Client(timeout=10.0) as client:
            while time.monotonic() < deadline:
                started = time.perf_counter()
                try:
                    response = client.post(
                        f"{BASE_URL}/contests/{contest_id}/problems/{pin_id}/submissions",
                        headers=headers,
                        json=body,
                    )
                    elapsed = (time.perf_counter() - started) * 1000
                    with lock:
                        latencies_ms.append(elapsed)
                        if response.status_code not in {200, 201}:
                            errors.append(f"HTTP {response.status_code}")
                except Exception as exc:
                    elapsed = (time.perf_counter() - started) * 1000
                    with lock:
                        latencies_ms.append(elapsed)
                        errors.append(type(exc).__name__)

    started = time.monotonic()
    threads = [threading.Thread(target=client_loop, name=f"load-client-{i + 1}") for i in range(CLIENTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started
    count = len(latencies_ms)
    report = "\n".join([
        f"started_at_utc: {datetime.now(timezone.utc).isoformat()}",
        f"duration_seconds: {elapsed:.2f}",
        f"concurrent_clients: {CLIENTS}",
        f"requests: {count}",
        f"p50_ms: {percentile(latencies_ms, 0.50):.2f}" if count else "p50_ms: n/a",
        f"p95_ms: {percentile(latencies_ms, 0.95):.2f}" if count else "p95_ms: n/a",
        f"p99_ms: {percentile(latencies_ms, 0.99):.2f}" if count else "p99_ms: n/a",
        f"requests_per_second: {count / elapsed:.2f}" if elapsed else "requests_per_second: 0.00",
        f"error_count: {len(errors)}",
        "execution_mode: docker-python",
    ])
    print(report)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report + "\n", encoding="utf-8")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
