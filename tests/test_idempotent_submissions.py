"""MySQL-backed submission idempotency tests, including concurrent HTTP requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.models import (
    Contest, ContestParticipant, ContestProblem, IdempotencyRecord, JudgeAttempt,
    Organization, OrganizationMembership, OutboxEvent, Problem, ProblemVersion,
    Submission, TestSuite as DbTestSuite, User,
)

PASSWORD = "Strong-Test-Password-2026"


def create_participant_contest(client):
    suffix = uuid4().hex
    email = f"idempotency-{suffix}@example.test"
    registered = client.post("/api/v1/auth/register", json={
        "name": "Idempotency Participant", "email": email, "password": PASSWORD,
    })
    assert registered.status_code == 201, registered.text
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        org = Organization(name=f"Idempotency Org {suffix}")
        db.add(org)
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
        db.flush()
        contest = Contest(
            organization_id=org.id, organizer_id=user.id, title=f"Idempotency {suffix}",
            start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1), status="published",
        )
        problem = Problem(organization_id=org.id, title=f"Problem {suffix}")
        db.add_all([contest, problem])
        db.flush()
        version = ProblemVersion(
            problem_id=problem.id, version_number=1, statement="s", execution_limits={},
            runtime_configuration={}, published_at=now,
        )
        db.add(version)
        db.flush()
        suite = DbTestSuite(problem_version_id=version.id, version_number=1, status="active")
        db.add(suite)
        db.flush()
        pin = ContestProblem(
            contest_id=contest.id, organization_id=org.id, problem_id=problem.id,
            problem_version_id=version.id, test_suite_id=suite.id, display_order=1, points=100,
        )
        db.add(pin)
        db.commit()
        contest_id, pin_id = contest.id, pin.id
    response = client.post(f"/api/v1/contests/{contest_id}/register", headers=headers)
    assert response.status_code == 201, response.text
    return contest_id, pin_id, headers


def post_submission(client, contest_id, pin_id, headers, source="print(1)\n", key="request-1"):
    return client.post(
        f"/api/v1/contests/{contest_id}/problems/{pin_id}/submissions",
        headers={**headers, "Idempotency-Key": key},
        json={"source_code": source, "language": "python"},
    )


def test_same_idempotency_key_replays_one_submission(client):
    contest_id, pin_id, headers = create_participant_contest(client)
    first = post_submission(client, contest_id, pin_id, headers)
    replay = post_submission(client, contest_id, pin_id, headers)
    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Submission.id)).where(Submission.contest_id == contest_id)) == 1
        assert db.scalar(select(func.count(JudgeAttempt.id)).where(JudgeAttempt.submission_id == first.json()["id"])) == 1
        assert db.scalar(select(func.count(OutboxEvent.id)).join(JudgeAttempt).where(JudgeAttempt.submission_id == first.json()["id"])) == 1
        assert db.scalar(select(func.count(IdempotencyRecord.id)).where(IdempotencyRecord.contest_id == contest_id)) == 1


def test_reused_key_with_different_source_conflicts(client):
    contest_id, pin_id, headers = create_participant_contest(client)
    first = post_submission(client, contest_id, pin_id, headers, "print(1)\n")
    changed = post_submission(client, contest_id, pin_id, headers, "print(2)\n")
    assert first.status_code == 201, first.text
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_reused_key_with_different_contest_problem_conflicts(client):
    contest_id, pin_id, headers = create_participant_contest(client)
    with SessionLocal() as db:
        original_pin = db.get(ContestProblem, pin_id)
        original_problem = db.get(Problem, original_pin.problem_id)
        problem = Problem(organization_id=original_problem.organization_id, title="Second pinned problem")
        db.add(problem)
        db.flush()
        version = ProblemVersion(
            problem_id=problem.id, version_number=1, statement="s", execution_limits={},
            runtime_configuration={}, published_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(version)
        db.flush()
        suite = DbTestSuite(problem_version_id=version.id, version_number=1, status="active")
        db.add(suite)
        db.flush()
        other_pin = ContestProblem(
            contest_id=contest_id, organization_id=original_pin.organization_id, problem_id=problem.id,
            problem_version_id=version.id, test_suite_id=suite.id, display_order=2, points=100,
        )
        db.add(other_pin)
        db.commit()
        other_pin_id = other_pin.id
    first = post_submission(client, contest_id, pin_id, headers, "print(1)\n", key="problem-scoped-key")
    changed_problem = post_submission(client, contest_id, other_pin_id, headers, "print(1)\n", key="problem-scoped-key")
    assert first.status_code == 201, first.text
    assert changed_problem.status_code == 409
    assert changed_problem.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_ten_concurrent_identical_requests_create_one_submission(client):
    contest_id, pin_id, headers = create_participant_contest(client)

    def send_request(_):
        # Each thread owns its own TestClient and therefore its own request DB session.
        with TestClient(app) as thread_client:
            return post_submission(thread_client, contest_id, pin_id, headers, key="concurrent-key")

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(send_request, range(10)))
    assert sorted(response.status_code for response in responses) == [200] * 9 + [201]
    assert len({response.json()["id"] for response in responses}) == 1
    assert sum(response.headers.get("Idempotent-Replayed") == "true" for response in responses) == 9
    with SessionLocal() as db:
        submission_id = responses[0].json()["id"]
        assert db.scalar(select(func.count(Submission.id)).where(Submission.contest_id == contest_id)) == 1
        assert db.scalar(select(func.count(JudgeAttempt.id)).where(JudgeAttempt.submission_id == submission_id)) == 1
        assert db.scalar(select(func.count(OutboxEvent.id)).join(JudgeAttempt).where(JudgeAttempt.submission_id == submission_id)) == 1
