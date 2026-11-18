"""Measure authenticated leaderboard GET latency against the perf seed contest."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contest

BASE_URL = os.getenv("EASECODING_API_URL", "http://localhost:8000/api/v1").rstrip("/")
CONTEST_TITLE = "Leaderboard EXPLAIN Perf Seed 2026-11-18"
CLIENTS = 10
REQUESTS_PER_CLIENT = 20
EMAIL = os.getenv("PERF_LOGIN_EMAIL", "participant@example.test")
PASSWORD = os.getenv("PERF_LOGIN_PASSWORD", "EasecodingDemo!2026")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    ratio = position - lower
    return ordered[lower] * (1 - ratio) + ordered[upper] * ratio


def main() -> int:
    with SessionLocal() as db:
        contest_id = db.scalar(
            select(Contest.id)
            .where(Contest.title == CONTEST_TITLE)
            .order_by(Contest.id.desc())
            .limit(1)
        )
    if contest_id is None:
        print("ERROR: perf seed contest not found; run python -m scripts.seed_perf first")
        return 1

    with httpx.Client(timeout=30) as client:
        login = client.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        token = login.json()["access_token"]

    latencies: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/contests/{contest_id}/leaderboard"

    def run_client() -> None:
        with httpx.Client(timeout=30) as client:
            local_latencies = []
            local_errors = []
            for _ in range(REQUESTS_PER_CLIENT):
                started = time.perf_counter()
                try:
                    response = client.get(url, headers=headers)
                    local_latencies.append((time.perf_counter() - started) * 1000)
                    if response.status_code != 200:
                        local_errors.append(f"HTTP {response.status_code}")
                except Exception as exc:
                    local_latencies.append((time.perf_counter() - started) * 1000)
                    local_errors.append(type(exc).__name__)
            with lock:
                latencies.extend(local_latencies)
                errors.extend(local_errors)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        list(pool.map(lambda _index: run_client(), range(CLIENTS)))
    elapsed = time.perf_counter() - started
    print(f"contest_id: {contest_id}")
    print(f"concurrent_clients: {CLIENTS}")
    print(f"requests_per_client: {REQUESTS_PER_CLIENT}")
    print(f"requests: {len(latencies)}")
    print(f"duration_seconds: {elapsed:.3f}")
    print(f"p50_ms: {percentile(latencies, 0.50):.3f}")
    print(f"p95_ms: {percentile(latencies, 0.95):.3f}")
    print(f"error_count: {len(errors)}")
    if errors:
        print(f"errors: {errors[:10]}")
    return 0 if len(latencies) == CLIENTS * REQUESTS_PER_CLIENT and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
