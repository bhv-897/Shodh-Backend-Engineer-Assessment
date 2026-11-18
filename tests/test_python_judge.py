"""MySQL-backed worker integration tests requiring a reachable Docker daemon."""
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.judge_runner import CaseResult, DockerPythonRunner
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, Organization,
    JudgeCaseResult, OrganizationMembership, OutboxEvent, Problem, ProblemVersion, Submission,
    TestCase as DbTestCase, TestSuite as DbTestSuite, User, Verdict,
)
from app.worker import MAX_RETRIES, process_one

PROGRAMS = [
    pytest.param("print('PRIVATE_EXPECTED')\n", "PRIVATE_EXPECTED\n", "ACCEPTED", 5.0, id="correct"),
    pytest.param("print('NO')\n", "PRIVATE_EXPECTED\n", "WRONG_ANSWER", 5.0, id="wrong-answer"),
    pytest.param("raise RuntimeError('student failure')\n", "PRIVATE_EXPECTED\n", "RUNTIME_ERROR", 5.0, id="runtime-error"),
    pytest.param("while True:\n    pass\n", "PRIVATE_EXPECTED\n", "TIME_LIMIT_EXCEEDED", 1.0, id="timeout"),
    pytest.param("print('x' * 70000)\n", "PRIVATE_EXPECTED\n", "RUNTIME_ERROR", 5.0, id="excessive-output"),
    pytest.param("def broken(:\n    pass\n", "PRIVATE_EXPECTED\n", "COMPILATION_ERROR", 5.0, id="compilation-error"),
]
requires_docker = pytest.mark.skipif(
    not os.path.exists("/var/run/docker.sock"),
    reason="real-Docker integration test requires the Docker socket (run in worker service)",
)


def queued_submission(source, expected="OK\n", timeout=5.0):
    suffix = uuid4().hex
    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        owner = User(email=f"judge-owner-{suffix}@example.test", name="Judge Owner", password_hash="test")
        participant_user = User(email=f"judge-participant-{suffix}@example.test", name="Judge Participant", password_hash="test")
        org = Organization(name=f"Judge Org {suffix}")
        db.add_all([owner, participant_user, org])
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
        db.flush()
        contest = Contest(organization_id=org.id, organizer_id=owner.id, title=f"Judge {suffix}", start_time=now, end_time=now + timedelta(hours=1), status="published")
        problem = Problem(organization_id=org.id, title=f"Problem {suffix}")
        db.add_all([contest, problem])
        db.flush()
        version = ProblemVersion(problem_id=problem.id, version_number=1, statement="s", execution_limits={}, runtime_configuration={"time_limit_seconds": timeout}, published_at=now)
        db.add(version)
        db.flush()
        suite = DbTestSuite(problem_version_id=version.id, version_number=1, status="draft")
        db.add(suite)
        db.flush()
        case = DbTestCase(test_suite_id=suite.id, identifier="hidden", input_data="PRIVATE_INPUT\n", expected_output=expected, is_hidden=True, points=100)
        db.add(case)
        db.flush()
        suite.status = "active"
        pin = ContestProblem(contest_id=contest.id, organization_id=org.id, problem_id=problem.id, problem_version_id=version.id, test_suite_id=suite.id, display_order=1, points=100)
        db.add(pin)
        db.flush()
        participant = ContestParticipant(contest_id=contest.id, user_id=participant_user.id, status="registered")
        db.add(participant)
        db.flush()
        submission = Submission(contest_participant_id=participant.id, contest_id=contest.id, contest_problem_id=pin.id, problem_version_id=version.id, test_suite_id=suite.id, source_code=source, language="python", runtime_config_snapshot={"time_limit_seconds": timeout})
        db.add(submission)
        db.flush()
        attempt = JudgeAttempt(submission_id=submission.id, attempt_number=1, reason="initial", status="queued")
        db.add(attempt)
        db.flush()
        event = OutboxEvent(judge_attempt_id=attempt.id, event_type="judge.requested", status="pending")
        db.add(event)
        db.commit()
        return event.id, attempt.id


@pytest.mark.parametrize("source,expected,expected_verdict,timeout", PROGRAMS)
@requires_docker
def test_worker_runs_python_program_types_in_docker(source, expected, expected_verdict, timeout):
    event_id, attempt_id = queued_submission(source, expected, timeout)
    assert process_one(DockerPythonRunner(timeout_seconds=5.0), event_id=event_id)
    with SessionLocal() as db:
        verdict = db.scalar(select(Verdict).where(Verdict.judge_attempt_id == attempt_id))
        event = db.get(OutboxEvent, event_id)
        case_result = db.scalar(select(JudgeCaseResult).where(JudgeCaseResult.judge_attempt_id == attempt_id))
        actual_verdict = verdict.verdict if verdict else None
        private_diagnostics = verdict.private_diagnostics if verdict else None
        assert actual_verdict == expected_verdict, (
            f"expected verdict={expected_verdict!r}, actual verdict={actual_verdict!r}, "
            f"private_diagnostics={private_diagnostics!r}"
        )
        assert event.status == "published"
        assert case_result.verdict == expected_verdict
        if expected_verdict in {"WRONG_ANSWER", "RUNTIME_ERROR", "TIME_LIMIT_EXCEEDED", "COMPILATION_ERROR"}:
            assert "PRIVATE_INPUT" in verdict.private_diagnostics
            assert "PRIVATE_EXPECTED" not in (verdict.public_message or "")


def test_fake_runner_failure_is_judge_infrastructure_failure():
    event_id, attempt_id = queued_submission("print('OK')\n")

    class UnavailableRunner:
        def run_case(self, *_args, **_kwargs):
            raise RuntimeError("docker daemon unavailable")

    assert process_one(UnavailableRunner(), event_id=event_id)
    with SessionLocal() as db:
        verdict = db.scalar(select(Verdict).where(Verdict.judge_attempt_id == attempt_id))
        assert verdict.verdict == "JUDGE_INFRA_FAILURE"
        assert "docker daemon unavailable" in verdict.private_diagnostics
        assert "PRIVATE_INPUT" not in (verdict.public_message or "")


@requires_docker
def test_runner_executes_submission_from_mounted_file():
    result = DockerPythonRunner(timeout_seconds=5.0).run_case("import sys; print(sys.argv[0])\n", "")
    assert result.verdict == "ACCEPTED"
    assert result.stdout.strip() == "/submission/main.py"


@requires_docker
def test_two_workers_racing_one_outbox_event_only_execute_it_once():
    event_id, attempt_id = queued_submission("import time; time.sleep(1); print('PRIVATE_EXPECTED')\n", "PRIVATE_EXPECTED\n")
    command = [sys.executable, "-m", "app.worker", "--once", "--event-id", str(event_id)]
    workers = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = [worker.communicate(timeout=30) for worker in workers]
    assert [worker.returncode for worker in workers] == [0, 0], outputs
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Verdict.id)).where(Verdict.judge_attempt_id == attempt_id)) == 1
        assert db.scalar(select(OutboxEvent.status).where(OutboxEvent.id == event_id)) == "published"


def test_expired_worker_lease_is_reclaimed_and_retried():
    event_id, attempt_id = queued_submission("print('PRIVATE_EXPECTED')\n", "PRIVATE_EXPECTED\n")
    with SessionLocal.begin() as db:
        db.execute(text("UPDATE judge_attempts SET status='running',worker_id='dead-worker',lease_token='old',lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE id=:id"), {"id": attempt_id})
        db.execute(text("UPDATE outbox_events SET status='processing' WHERE id=:id"), {"id": event_id})

    class FastRunner:
        def run_case(self, *_args, **_kwargs):
            return CaseResult("ACCEPTED", "PRIVATE_EXPECTED\n", execution_time_ms=1)

    assert process_one(FastRunner(), event_id=event_id)
    with SessionLocal() as db:
        attempt = db.get(JudgeAttempt, attempt_id)
        assert attempt.status == "completed" and attempt.retry_count == 1
        assert db.get(OutboxEvent, event_id).status == "published"


def test_exhausted_recovery_writes_infrastructure_verdict():
    event_id, attempt_id = queued_submission("print('PRIVATE_EXPECTED')\n", "PRIVATE_EXPECTED\n")
    with SessionLocal.begin() as db:
        db.execute(text("UPDATE judge_attempts SET status='running',worker_id='dead-worker',lease_token='old',lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND,retry_count=:retries WHERE id=:id"), {"retries": MAX_RETRIES, "id": attempt_id})
        db.execute(text("UPDATE outbox_events SET status='processing' WHERE id=:id"), {"id": event_id})
    assert process_one(object(), event_id=event_id)
    with SessionLocal() as db:
        verdict = db.scalar(select(Verdict).where(Verdict.judge_attempt_id == attempt_id))
        assert verdict.verdict == "JUDGE_INFRA_FAILURE"
        assert "bounded recovery retry limit" in verdict.private_diagnostics
        assert db.get(OutboxEvent, event_id).status == "published"


def test_replay_publishes_event_if_verdict_committed_before_worker_restart():
    event_id, attempt_id = queued_submission("print('PRIVATE_EXPECTED')\n", "PRIVATE_EXPECTED\n")
    with SessionLocal() as db:
        db.execute(text("UPDATE judge_attempts SET status='running',worker_id='old-worker',lease_token='old',lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE id=:id"), {"id": attempt_id})
        db.commit()
        from app.services.verdicts import record_verdict
        record_verdict(db, attempt_id, "ACCEPTED", score=100, lease_token="old")
        db.execute(text("UPDATE outbox_events SET status='processing' WHERE id=:id"), {"id": event_id})
        db.commit()
    assert process_one(event_id=event_id)
    with SessionLocal() as db:
        assert db.get(OutboxEvent, event_id).status == "published"
        assert db.scalar(select(Verdict.id).where(Verdict.judge_attempt_id == attempt_id)) is not None
