"""MySQL-backed rejudge API and authoritative-attempt tests."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, Organization,
    OrganizationMembership, OutboxEvent, Problem, ProblemVersion, Submission,
    TestSuite as DbTestSuite, User,
)
from app.services.verdicts import record_verdict

PASSWORD = "Strong-Test-Password-2026"


def auth_user(client, label):
    email = f"rejudge-{label}-{uuid4().hex}@example.test"
    created = client.post("/api/v1/auth/register", json={"name": label, "email": email, "password": PASSWORD})
    assert created.status_code == 201, created.text
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


def rejudge_fixture(client):
    owner_email, owner_headers = auth_user(client, "owner")
    organizer_email, organizer_headers = auth_user(client, "organizer")
    participant_email, participant_headers = auth_user(client, "participant")
    member_email, member_headers = auth_user(client, "member")
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == owner_email))
        organizer = db.scalar(select(User).where(User.email == organizer_email))
        participant_user = db.scalar(select(User).where(User.email == participant_email))
        member_user = db.scalar(select(User).where(User.email == member_email))
        org = Organization(name=f"Rejudge Org {uuid4().hex}")
        db.add(org)
        db.flush()
        db.add_all([
            OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"),
            OrganizationMembership(organization_id=org.id, user_id=organizer.id, role="organizer"),
            OrganizationMembership(organization_id=org.id, user_id=member_user.id, role="member"),
        ])
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        contest = Contest(
            organization_id=org.id, organizer_id=organizer.id, title="Rejudge contest",
            start_time=now-timedelta(hours=1), end_time=now+timedelta(hours=1), status="published",
        )
        problem = Problem(organization_id=org.id, title="Rejudge problem")
        db.add_all([contest, problem])
        db.flush()
        version = ProblemVersion(
            problem_id=problem.id, version_number=1, statement="s", execution_limits={},
            runtime_configuration={"python": "3.12"}, published_at=now,
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
        db.flush()
        participant = ContestParticipant(contest_id=contest.id, user_id=participant_user.id, status="registered")
        db.add(participant)
        db.flush()
        submission = Submission(
            contest_participant_id=participant.id, contest_id=contest.id, contest_problem_id=pin.id,
            problem_version_id=version.id, test_suite_id=suite.id, source_code="print(1)\n",
            language="python", runtime_config_snapshot=version.runtime_configuration, status="completed",
        )
        db.add(submission)
        db.flush()
        first = JudgeAttempt(
            submission_id=submission.id, attempt_number=1, reason="initial", requested_by_user_id=participant_user.id,
            status="completed", completed_at=now,
        )
        db.add(first)
        db.commit()
        return {
            "submission_id": submission.id,
            "attempt1_id": first.id,
            "contest_problem_id": pin.id,
            "problem_version_id": version.id,
            "test_suite_id": suite.id,
            "organizer_id": organizer.id,
            "organizer_headers": organizer_headers,
            "owner_headers": owner_headers,
            "participant_headers": participant_headers,
            "member_headers": member_headers,
        }


def test_organizer_rejudge_creates_attempt_two_with_original_pin(client):
    fixture = rejudge_fixture(client)
    response = client.post(
        f"/api/v1/submissions/{fixture['submission_id']}/rejudge",
        headers=fixture["organizer_headers"],
        json={"problem_version_id": fixture["problem_version_id"], "test_suite_id": fixture["test_suite_id"]},
    )
    assert response.status_code == 202, response.text
    attempt = response.json()
    assert attempt["attempt_number"] == 2
    assert attempt["reason"] == "rejudge"
    assert attempt["requested_by_user_id"] == fixture["organizer_id"]
    assert attempt["status"] == "queued"
    with SessionLocal() as db:
        submission = db.get(Submission, fixture["submission_id"])
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.judge_attempt_id == attempt["id"]))
        assert (submission.contest_problem_id, submission.problem_version_id, submission.test_suite_id) == (
            fixture["contest_problem_id"], fixture["problem_version_id"], fixture["test_suite_id"],
        )
        assert event is not None and event.event_type == "judge.requested" and event.status == "pending"


def test_participant_gets_404_and_member_gets_403_from_rejudge(client):
    fixture = rejudge_fixture(client)
    # Participants have no organization role; org-scoped resources are hidden as 404.
    response = client.post(f"/api/v1/submissions/{fixture['submission_id']}/rejudge", headers=fixture["participant_headers"])
    assert response.status_code == 404
    member_response = client.post(f"/api/v1/submissions/{fixture['submission_id']}/rejudge", headers=fixture["member_headers"])
    assert member_response.status_code == 403


def test_rejudge_rejects_values_different_from_the_submission_pin(client):
    fixture = rejudge_fixture(client)
    response = client.post(
        f"/api/v1/submissions/{fixture['submission_id']}/rejudge",
        headers=fixture["owner_headers"], json={"problem_version_id": fixture["problem_version_id"] + 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PIN_MISMATCH"


def test_rejudge_is_rejected_while_attempt_two_is_queued(client):
    fixture = rejudge_fixture(client)
    url = f"/api/v1/submissions/{fixture['submission_id']}/rejudge"
    first = client.post(url, headers=fixture["owner_headers"])
    second = client.post(url, headers=fixture["organizer_headers"])
    assert first.status_code == 202, first.text
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ATTEMPT_IN_PROGRESS"


def test_late_attempt_one_verdict_does_not_replace_attempt_two(client):
    fixture = rejudge_fixture(client)
    response = client.post(f"/api/v1/submissions/{fixture['submission_id']}/rejudge", headers=fixture["organizer_headers"])
    assert response.status_code == 202, response.text
    attempt2_id = response.json()["id"]
    with SessionLocal() as db:
        record_verdict(db, attempt2_id, "ACCEPTED", score=100)
    # Simulate a delayed completion from attempt 1 after the newer result commits.
    with SessionLocal.begin() as db:
        db.execute(update(JudgeAttempt).where(JudgeAttempt.id == fixture["attempt1_id"]).values(status="running"))
    with SessionLocal() as db:
        record_verdict(db, fixture["attempt1_id"], "WRONG_ANSWER", score=0)
    with SessionLocal() as db:
        submission = db.get(Submission, fixture["submission_id"])
        assert submission.authoritative_attempt_id == attempt2_id
