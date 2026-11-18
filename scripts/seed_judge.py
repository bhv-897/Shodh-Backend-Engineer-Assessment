"""Create three runnable Python problems plus five unjudged sample programs."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, Organization,
    OrganizationMembership, OutboxEvent, Problem, ProblemVersion, Submission,
    TestCase, TestSuite, User,
)

ORG_NAME = "Easecoding Judge Demo Organization"
CONTEST_TITLE = "Easecoding Judge Demo Contest"
PROGRAMS = [
    ("Correct Output", "print('OK')\n", "AC test", 5.0),
    ("Wrong Output", "print('NO')\n", "WA test", 5.0),
    ("Runtime Error", "raise RuntimeError('sample runtime failure')\n", "RE test", 5.0),
    ("Time Limit", "while True:\n    pass\n", "TLE test", 1.0),
    ("Output Limit", "print('x' * 70000)\n", "output cap test", 5.0),
]


def main():
    with SessionLocal.begin() as db:
        existing = db.scalar(select(Contest).where(Contest.title == CONTEST_TITLE))
        if existing:
            print(f"Already seeded contest_id={existing.id}")
            return

        owner = User(email="judge-demo-owner@example.test", name="Judge Demo Owner", password_hash="seed-only")
        participant_user = User(email="judge-demo-participant@example.test", name="Judge Demo Participant", password_hash="seed-only")
        org = Organization(name=ORG_NAME)
        db.add_all([owner, participant_user, org])
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner"))
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        contest = Contest(
            organization_id=org.id, organizer_id=owner.id, title=CONTEST_TITLE,
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(days=1), status="published",
            scoring_mode="icpc", penalty_minutes_per_wrong=20,
        )
        db.add(contest)
        db.flush()
        participant = ContestParticipant(contest_id=contest.id, user_id=participant_user.id, status="registered")
        db.add(participant)

        pins = []
        for i in range(3):
            problem = Problem(organization_id=org.id, title=f"Judge Demo Problem {i + 1}")
            db.add(problem)
            db.flush()
            version = ProblemVersion(
                problem_id=problem.id, version_number=1, statement="Print OK for the sample test.",
            execution_limits={"time_limit_seconds": 5}, runtime_configuration={"time_limit_seconds": 5.0},
                published_at=now,
            )
            db.add(version)
            db.flush()
            suite = TestSuite(problem_version_id=version.id, version_number=1, status="draft")
            db.add(suite)
            db.flush()
            db.add(TestCase(test_suite_id=suite.id, identifier="sample", input_data="", expected_output="OK\n", is_hidden=False, points=100))
            db.flush()
            suite.status = "active"
            pin = ContestProblem(
                contest_id=contest.id, organization_id=org.id, problem_id=problem.id,
                problem_version_id=version.id, test_suite_id=suite.id, display_order=i + 1, points=100,
            )
            db.add(pin)
            db.flush()
            pins.append(pin)

        for index, (label, program, _, timeout) in enumerate(PROGRAMS):
            pin = pins[index % len(pins)]
            submission = Submission(
                contest_participant_id=participant.id, contest_id=contest.id, contest_problem_id=pin.id,
                problem_version_id=pin.problem_version_id, test_suite_id=pin.test_suite_id,
                source_code=program, language="python", runtime_config_snapshot={"time_limit_seconds": timeout},
            )
            db.add(submission)
            db.flush()
            attempt = JudgeAttempt(submission_id=submission.id, attempt_number=1, reason="initial", requested_by_user_id=participant_user.id, status="queued")
            db.add(attempt)
            db.flush()
            db.add(OutboxEvent(judge_attempt_id=attempt.id, event_type="judge.requested", status="pending"))
            print(f"Queued {label}: submission_id={submission.id} attempt_id={attempt.id}")

        print(f"Seeded contest_id={contest.id}, participants=1, problems=3, sample_submissions={len(PROGRAMS)}")


if __name__ == "__main__":
    main()
