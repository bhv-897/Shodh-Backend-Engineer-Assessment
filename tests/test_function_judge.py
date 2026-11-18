"""Real-Docker tests for LeetCode-style function submission execution."""
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.judge_runner import DockerPythonRunner
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, JudgeCaseResult,
    Organization, OrganizationMembership, OutboxEvent, Problem, ProblemVersion,
    Submission, TestCase as DbTestCase, TestSuite as DbTestSuite, User, Verdict,
)
from app.worker import process_one
from scripts.seed_dev import PROBLEMS

requires_docker = pytest.mark.skipif(
    not os.path.exists("/var/run/docker.sock"),
    reason="function judge integration tests require the Docker socket",
)

CORRECT = """def reverse_list(head):
    previous = None
    while head is not None:
        following = head.next
        head.next = previous
        previous = head
        head = following
    return previous
"""
WRONG = "def reverse_list(head):\n    return head\n"
SYNTAX_ERROR = "def reverse_list(:\n    pass\n"
MISSING_FUNCTION = "def reverse_nodes(head):\n    return head\n"


def queue_function_submission(source):
    suffix = uuid4().hex
    spec = PROBLEMS["Reverse Linked List"]
    runtime = {
        "python": "3.12", "execution_mode": "function",
        "function_name": "reverse_list", "function_driver": "linked_list",
        "time_limit_seconds": 5.0,
    }
    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        owner = User(email=f"function-owner-{suffix}@example.test", name="Function Owner", password_hash="test")
        participant_user = User(email=f"function-participant-{suffix}@example.test", name="Function Participant", password_hash="test")
        org = Organization(name=f"Function Org {suffix}")
        db.add_all([owner, participant_user, org])
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
        db.flush()
        contest = Contest(
            organization_id=org.id, organizer_id=owner.id, title=f"Function contest {suffix}",
            start_time=now, end_time=now+timedelta(hours=1), status="published",
        )
        problem = Problem(organization_id=org.id, title="Reverse Linked List")
        db.add_all([contest, problem])
        db.flush()
        version = ProblemVersion(
            problem_id=problem.id, version_number=1, statement=spec["statement"],
            execution_limits={"time_ms": 5000, "memory_mb": 128},
            runtime_configuration=runtime, published_at=now,
        )
        db.add(version)
        db.flush()
        suite = DbTestSuite(problem_version_id=version.id, version_number=1, status="draft")
        db.add(suite)
        db.flush()
        cases = []
        for case_spec in spec["cases"]:
            case = DbTestCase(test_suite_id=suite.id, **case_spec)
            db.add(case)
            cases.append(case)
        db.flush()
        suite.status = "active"
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
            problem_version_id=version.id, test_suite_id=suite.id, source_code=source,
            language="python", runtime_config_snapshot=runtime,
        )
        db.add(submission)
        db.flush()
        attempt = JudgeAttempt(submission_id=submission.id, attempt_number=1, reason="initial", status="queued")
        db.add(attempt)
        db.flush()
        event = OutboxEvent(judge_attempt_id=attempt.id, event_type="judge.requested", status="pending")
        db.add(event)
        db.commit()
        return event.id, attempt.id, len(cases)


@requires_docker
@pytest.mark.parametrize(
    "source,expected_verdict,expected_message",
    [
        pytest.param(CORRECT, "ACCEPTED", None, id="correct-reverse-list"),
        pytest.param(WRONG, "WRONG_ANSWER", None, id="wrong-reverse-list"),
        pytest.param(SYNTAX_ERROR, "COMPILATION_ERROR", None, id="syntax-error"),
        pytest.param(MISSING_FUNCTION, "COMPILATION_ERROR", "Function reverse_list not found", id="missing-function"),
    ],
)
def test_worker_judges_reverse_linked_list_programs(source, expected_verdict, expected_message):
    event_id, attempt_id, expected_case_count = queue_function_submission(source)
    assert process_one(DockerPythonRunner(timeout_seconds=6.0), event_id=event_id)
    with SessionLocal() as db:
        verdict = db.scalar(select(Verdict).where(Verdict.judge_attempt_id == attempt_id))
        event = db.get(OutboxEvent, event_id)
        case_results = list(db.scalars(
            select(JudgeCaseResult).where(JudgeCaseResult.judge_attempt_id == attempt_id).order_by(JudgeCaseResult.ordinal)
        ))
        assert verdict.verdict == expected_verdict
        assert event.status == "published"
        if expected_message:
            assert verdict.public_message == expected_message
        if expected_verdict == "ACCEPTED":
            assert len(case_results) == expected_case_count == 7
            assert all(row.verdict == "ACCEPTED" for row in case_results)
        else:
            assert len(case_results) == 1
