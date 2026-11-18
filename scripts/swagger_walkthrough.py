"""Run the Stage 1 Swagger/API flow and save redacted request evidence."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.getenv("EASECODING_API_URL", "http://localhost:8000/api/v1").rstrip("/")
PASSWORD = os.getenv("EASECODING_WALKTHROUGH_PASSWORD", "Walkthrough-Password-2026")
EVIDENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "swagger_walkthrough.txt"
REDACTED_KEYS = {"password", "password_hash", "access_token", "refresh_token", "token", "authorization"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in REDACTED_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def body_for(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return redact(response.json())
    except ValueError:
        return response.text


def main() -> int:
    output: list[str] = []

    def record(label: str, response: httpx.Response) -> Any:
        body = body_for(response)
        block="\n".join([f"=== {label} ===",f"status: {response.status_code} {response.reason_phrase}","body:",json.dumps(body, indent=2, ensure_ascii=False) if body is not None else "<empty>",""])
        output.append(block)
        print(block, flush=True)
        if not response.is_success:
            raise RuntimeError(f"{label} failed with HTTP {response.status_code}")
        return response.json() if response.content else None

    try:
        now = datetime.now(timezone.utc)
        email = f"swagger-walkthrough-{uuid.uuid4().hex}@example.test"
        with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
            registration = record("Register owner", client.post("/auth/register", json={"name": "Swagger Walkthrough Owner", "email": email, "password": PASSWORD}))
            login = record("Login owner", client.post("/auth/login", json={"email": email, "password": PASSWORD}))
            headers = {"Authorization": f"Bearer {login['access_token']}"}

            org = record("Create organization", client.post("/organizations", headers=headers, json={"name": f"Swagger Walkthrough {uuid.uuid4().hex[:8]}"}))
            problem = record("Create problem", client.post(f"/organizations/{org['id']}/problems", headers=headers, json={"title": "Walkthrough: Add Two Numbers"}))
            version = record("Create problem version", client.post(f"/problems/{problem['id']}/versions", headers=headers, json={"statement": "Read two integers and print their sum.", "execution_limits": {"time_ms": 1000, "memory_mb": 128}, "runtime_configuration": {"python": "3.12"}}))
            published_version = record("Publish problem version", client.post(f"/problem-versions/{version['id']}/publish", headers=headers))
            suite = record("Create test suite", client.post(f"/problem-versions/{version['id']}/test-suites", headers=headers))
            test_case = record("Create test case", client.post(f"/test-suites/{suite['id']}/test-cases", headers=headers, json={"identifier": "sample-1", "input_data": "2 3\n", "expected_output": "5\n", "is_hidden": False, "points": 100}))
            active_suite = record("Activate test suite", client.post(f"/test-suites/{suite['id']}/activate", headers=headers))

            start_time = (now - timedelta(minutes=5)).isoformat()
            end_time = (now + timedelta(hours=2)).isoformat()
            contest = record("Create contest", client.post(f"/organizations/{org['id']}/contests", headers=headers, json={"title": "Swagger Walkthrough Contest", "start_time": start_time, "end_time": end_time, "scoring_mode": "icpc", "penalty_minutes_per_wrong": 20}))
            pin = record("Add contest problem", client.post(f"/contests/{contest['id']}/problems", headers=headers, json={"problem_id": problem["id"], "problem_version_id": published_version["id"], "test_suite_id": active_suite["id"], "display_order": 1, "points": 100}))
            published_contest = record("Publish contest", client.post(f"/contests/{contest['id']}/publish", headers=headers))
            participant = record("Register participant", client.post(f"/contests/{contest['id']}/register", headers=headers))
            submission = record("Submit Python solution", client.post(f"/contests/{contest['id']}/problems/{pin['id']}/submissions", headers=headers, json={"source_code": "a, b = map(int, input().split())\nprint(a + b)\n", "language": "python"}))
            attempts = record("Fetch submission attempts", client.get(f"/submissions/{submission['id']}/attempts", headers=headers))
            attempt_id = attempts["items"][0]["id"]
            verdict = record("Record development verdict", client.post(f"/dev/attempts/{attempt_id}/verdict", headers=headers, json={"verdict": "ACCEPTED", "score": 100, "execution_time_ms": 1, "memory_used_kb": 1024, "public_message": "Accepted", "private_diagnostics": "Walkthrough test verdict"}))
            leaderboard = record("Fetch leaderboard", client.get(f"/contests/{contest['id']}/leaderboard", headers=headers))

        output.append("Walkthrough completed successfully.")
        print("Walkthrough completed successfully.", flush=True)
        return 0
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        message = f"Walkthrough stopped: {type(exc).__name__}: {exc}"
        output.extend([message, ""])
        print(message, file=sys.stderr, flush=True)
        return 1
    finally:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text("\n".join(output), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
