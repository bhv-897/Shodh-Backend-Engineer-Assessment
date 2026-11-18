"""Integration checks for cross-organization and participant access boundaries."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, JudgeCaseResult,
    Organization, OrganizationMembership, Problem, ProblemVersion, Submission,
    TestCase as DbTestCase, TestSuite as DbTestSuite, User, Verdict,
)

PASSWORD = "Strong-Test-Password-2026"


def new_auth_user(client, name):
    email = f"{name}-{uuid4().hex}@example.test"
    response = client.post("/api/v1/auth/register", json={"name": name, "email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


def create_contest_graph(db, owner, label):
    suffix = uuid4().hex
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    org = Organization(name=f"{label} {suffix}")
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
    db.flush()
    contest = Contest(
        organization_id=org.id, organizer_id=owner.id, title=label,
        start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1), status="published",
    )
    problem = Problem(organization_id=org.id, title=label)
    db.add_all([contest, problem])
    db.flush()
    version = ProblemVersion(
        problem_id=problem.id, version_number=1, statement="s", execution_limits={},
        runtime_configuration={}, published_at=now,
    )
    db.add(version)
    db.flush()
    suite = DbTestSuite(problem_version_id=version.id, version_number=1, status="draft")
    db.add(suite)
    db.flush()
    visible = DbTestCase(test_suite_id=suite.id, identifier="public", input_data="1\n", expected_output="1\n", is_hidden=False, points=1)
    hidden = DbTestCase(test_suite_id=suite.id, identifier="hidden", input_data="secret input\n", expected_output="HIDDEN_EXPECTED_OUTPUT_SECRET\n", is_hidden=True, points=1)
    db.add_all([visible, hidden])
    db.flush()
    suite.status = "active"
    db.flush()
    pin = ContestProblem(
        contest_id=contest.id, organization_id=org.id, problem_id=problem.id,
        problem_version_id=version.id, test_suite_id=suite.id, display_order=1, points=2,
    )
    db.add(pin)
    db.flush()
    return contest, pin, hidden


def add_submission(db, contest, pin, participant, hidden_case=None):
    submission = Submission(
        contest_participant_id=participant.id, contest_id=contest.id, contest_problem_id=pin.id,
        problem_version_id=pin.problem_version_id, test_suite_id=pin.test_suite_id,
        source_code="print(1)", language="python", runtime_config_snapshot={},
        status="completed" if hidden_case else "queued",
    )
    db.add(submission)
    db.flush()
    if hidden_case:
        attempt = JudgeAttempt(submission_id=submission.id, attempt_number=1, reason="initial", status="completed")
        db.add(attempt)
        db.flush()
        submission.authoritative_attempt_id = attempt.id
        db.add(Verdict(
            judge_attempt_id=attempt.id, verdict="ACCEPTED", score=100,
            public_message="Accepted.", private_diagnostics="HIDDEN_EXPECTED_OUTPUT_SECRET; private stderr secret",
        ))
        db.add(JudgeCaseResult(judge_attempt_id=attempt.id, test_case_id=hidden_case.id, ordinal=1, verdict="ACCEPTED", execution_time_ms=1))
        db.flush()
    return submission


def register_participant(client, contest_id, headers):
    response = client.post(f"/api/v1/contests/{contest_id}/register", headers=headers)
    assert response.status_code == 201, response.text


def test_organizer_of_another_organization_gets_404_for_submission(client):
    _, organizer_a_headers = new_auth_user(client, "org-a-organizer")
    _, participant_headers = new_auth_user(client, "org-b-participant")
    organizer_a_email = client.get("/api/v1/auth/me", headers=organizer_a_headers).json()["email"]
    participant_email = client.get("/api/v1/auth/me", headers=participant_headers).json()["email"]
    with SessionLocal() as db:
        organizer_a = db.scalar(select(User).where(User.email == organizer_a_email))
        participant_user = db.scalar(select(User).where(User.email == participant_email))
        org_a = Organization(name=f"A-{uuid4().hex}")
        db.add(org_a)
        db.flush()
        db.add(OrganizationMembership(organization_id=org_a.id, user_id=organizer_a.id, role="owner"))
        contest_b, pin_b, _ = create_contest_graph(db, participant_user, "Organization B")
        participant = ContestParticipant(contest_id=contest_b.id, user_id=participant_user.id, status="registered")
        db.add(participant)
        db.flush()
        submission = add_submission(db, contest_b, pin_b, participant)
        submission_id = submission.id
        db.commit()
    assert client.get(f"/api/v1/submissions/{submission_id}", headers=organizer_a_headers).status_code == 404


def test_participant_gets_404_from_organizer_only_participant_list(client):
    _, owner_headers = new_auth_user(client, "contest-owner")
    _, participant_headers = new_auth_user(client, "contest-participant")
    owner_email = client.get("/api/v1/auth/me", headers=owner_headers).json()["email"]
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == owner_email))
        contest, _, _ = create_contest_graph(db, owner, "Participant policy")
        contest_id = contest.id
        db.commit()
    register_participant(client, contest_id, participant_headers)
    # Participants have no organization membership; the resource is hidden by org policy.
    assert client.get(f"/api/v1/contests/{contest_id}/participants", headers=participant_headers).status_code == 404


def test_owner_only_member_endpoint_returns_403_for_organizer_and_404_for_nonmember(client):
    _, owner_headers = new_auth_user(client, "membership-owner")
    organizer_email, organizer_headers = new_auth_user(client, "membership-organizer")
    _, nonmember_headers = new_auth_user(client, "membership-nonmember")
    organization = client.post("/api/v1/organizations", headers=owner_headers, json={"name": f"Role check {uuid4().hex}"})
    assert organization.status_code == 201, organization.text
    org_id = organization.json()["id"]
    added = client.post(
        f"/api/v1/organizations/{org_id}/members", headers=owner_headers,
        json={"email": organizer_email, "role": "organizer"},
    )
    assert added.status_code == 201, added.text
    request = {"email": f"target-{uuid4().hex}@example.test", "role": "member"}
    assert client.post(f"/api/v1/organizations/{org_id}/members", headers=organizer_headers, json=request).status_code == 403
    assert client.post(f"/api/v1/organizations/{org_id}/members", headers=nonmember_headers, json=request).status_code == 404


def test_participant_gets_404_for_another_participants_submission(client):
    _, owner_headers = new_auth_user(client, "same-contest-owner")
    _, reader_headers = new_auth_user(client, "submission-reader")
    _, other_headers = new_auth_user(client, "submission-other")
    owner_email = client.get("/api/v1/auth/me", headers=owner_headers).json()["email"]
    reader_email = client.get("/api/v1/auth/me", headers=reader_headers).json()["email"]
    other_email = client.get("/api/v1/auth/me", headers=other_headers).json()["email"]
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == owner_email))
        reader = db.scalar(select(User).where(User.email == reader_email))
        other = db.scalar(select(User).where(User.email == other_email))
        contest, pin, _ = create_contest_graph(db, owner, "Submission privacy")
        reader_participant = ContestParticipant(contest_id=contest.id, user_id=reader.id, status="registered")
        other_participant = ContestParticipant(contest_id=contest.id, user_id=other.id, status="registered")
        db.add_all([reader_participant, other_participant])
        db.flush()
        submission = add_submission(db, contest, pin, other_participant)
        submission_id = submission.id
        contest_id = contest.id
        db.commit()
    assert client.get(f"/api/v1/submissions/{submission_id}", headers=reader_headers).status_code == 404
    assert client.get(f"/api/v1/contests/{contest_id}/submissions", headers=reader_headers).status_code == 200


def test_participant_result_hides_hidden_case_and_expected_output(client):
    _, owner_headers = new_auth_user(client, "result-owner")
    _, participant_headers = new_auth_user(client, "result-participant")
    owner_email = client.get("/api/v1/auth/me", headers=owner_headers).json()["email"]
    participant_email = client.get("/api/v1/auth/me", headers=participant_headers).json()["email"]
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == owner_email))
        participant_user = db.scalar(select(User).where(User.email == participant_email))
        contest, pin, hidden = create_contest_graph(db, owner, "Hidden result")
        participant = ContestParticipant(contest_id=contest.id, user_id=participant_user.id, status="registered")
        db.add(participant)
        db.flush()
        submission = add_submission(db, contest, pin, participant, hidden)
        submission_id = submission.id
        db.commit()
    result = client.get(f"/api/v1/submissions/{submission_id}/result", headers=participant_headers)
    assert result.status_code == 200, result.text
    assert result.json()["result"] == {"verdict": "ACCEPTED", "public_message": "Accepted."}
    assert result.json()["cases"] == []
    assert "HIDDEN_EXPECTED_OUTPUT_SECRET" not in result.text
    assert "private stderr secret" not in result.text
