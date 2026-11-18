"""Recompute a contest leaderboard from authoritative database verdicts and compare the API."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contest, ContestParticipant, JudgeAttempt, Submission, User, Verdict

SEED_CONTEST_TITLE = "Easecoding Demo Contest A"
DEFAULT_EMAIL = "owner@example.test"
DEFAULT_PASSWORD = "EasecodingDemo!2026"


def calculate_standings(db, contest: Contest) -> list[dict]:
    participants = db.execute(
        select(ContestParticipant.id, ContestParticipant.user_id)
        .where(ContestParticipant.contest_id == contest.id, ContestParticipant.status == "registered")
    ).all()
    participant_ids = {participant_id for participant_id, _ in participants}
    rows = db.execute(
        select(
            Submission.contest_participant_id,
            Submission.contest_problem_id,
            Submission.id,
            Submission.submitted_at,
            Verdict.verdict,
        )
        .join(JudgeAttempt, JudgeAttempt.id == Submission.authoritative_attempt_id)
        .join(Verdict, Verdict.judge_attempt_id == JudgeAttempt.id)
        .where(Submission.contest_id == contest.id)
        .order_by(Submission.submitted_at, Submission.id)
    ).all()
    by_participant_problem = defaultdict(list)
    for participant_id, problem_id, submission_id, submitted_at, verdict in rows:
        if participant_id in participant_ids:
            by_participant_problem[(participant_id, problem_id)].append((submitted_at, submission_id, verdict))

    solved_by_participant = defaultdict(list)
    wrong_counts = defaultdict(int)
    for (participant_id, problem_id), submissions in by_participant_problem.items():
        accepted = next((index for index, row in enumerate(submissions) if row[2] == "ACCEPTED"), None)
        if accepted is None:
            continue
        solved_at, submission_id, _ = submissions[accepted]
        solved_by_participant[participant_id].append((problem_id, solved_at, submission_id))
        wrong_counts[participant_id] += sum(
            1 for _, _, verdict in submissions[:accepted]
            if verdict not in {"ACCEPTED", "JUDGE_INFRA_FAILURE"}
        )

    result = []
    for participant_id, user_id in participants:
        solves = solved_by_participant[participant_id]
        solve_minutes = sum(int((solved_at - contest.start_time).total_seconds() // 60) for _, solved_at, _ in solves)
        penalty = solve_minutes + wrong_counts[participant_id] * contest.penalty_minutes_per_wrong
        last_solved_at = max((solved_at for _, solved_at, _ in solves), default=None)
        result.append({
            "participant_id": participant_id,
            "user_id": user_id,
            "solved": len(solves),
            "penalty": penalty,
            "last_solved_at": last_solved_at,
        })
    result.sort(key=lambda row: (
        -row["solved"], row["penalty"], row["last_solved_at"] is None,
        row["last_solved_at"] or datetime.max, row["participant_id"],
    ))
    return result


def fetch_api_standings(base_url: str, contest_id: int, email: str, password: str) -> list[dict]:
    with httpx.Client(timeout=15.0) as client:
        login = client.post(f"{base_url}/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        cursor = None
        rows = []
        while True:
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{base_url}/contests/{contest_id}/leaderboard", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload["items"])
            cursor = payload.get("next_cursor")
            if not cursor:
                return rows


def compare(expected: list[dict], actual: list[dict]) -> bool:
    fields = ("participant_id", "user_id", "solved", "penalty", "last_solved_at")
    okay = True
    if len(expected) != len(actual):
        okay = False
        print(f"ROW_COUNT mismatch: expected={len(expected)} actual={len(actual)}")
    for index in range(max(len(expected), len(actual))):
        expected_row = expected[index] if index < len(expected) else None
        actual_row = actual[index] if index < len(actual) else None
        differences = {}
        if expected_row is None or actual_row is None:
            differences["row"] = {"expected": expected_row, "actual": actual_row}
        else:
            for field in fields:
                expected_value = expected_row[field]
                actual_value = actual_row.get(field)
                if field == "last_solved_at" and actual_value is not None:
                    actual_value = datetime.fromisoformat(actual_value)
                if expected_value != actual_value:
                    differences[field] = {
                        "expected": expected_value.isoformat() if isinstance(expected_value, datetime) else expected_value,
                        "actual": actual_row.get(field),
                    }
        if differences:
            okay = False
            print(f"ROW {index + 1} mismatch: {json.dumps(differences, sort_keys=True, default=str)}")
    return okay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contest-id", type=int, help="defaults to the latest seeded demo contest")
    parser.add_argument("--base-url", default=os.getenv("EASECODING_API_URL", "http://localhost:8000/api/v1").rstrip("/"))
    parser.add_argument("--email", default=os.getenv("EASECODING_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--password", default=os.getenv("EASECODING_PASSWORD", DEFAULT_PASSWORD))
    args = parser.parse_args()

    with SessionLocal() as db:
        contest = db.get(Contest, args.contest_id) if args.contest_id else db.scalar(
            select(Contest).where(Contest.title == SEED_CONTEST_TITLE).order_by(Contest.id.desc()).limit(1)
        )
        if contest is None:
            print("ERROR: seeded contest not found; run python -m scripts.seed_dev first")
            return 1
        contest_id = contest.id
        expected = calculate_standings(db, contest)
    try:
        actual = fetch_api_standings(args.base_url, contest_id, args.email, args.password)
    except Exception as exc:
        print(f"ERROR: unable to fetch API standings: {type(exc).__name__}: {exc}")
        return 1
    if compare(expected, actual):
        print(f"MATCH: contest_id={contest_id}, rows={len(expected)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
