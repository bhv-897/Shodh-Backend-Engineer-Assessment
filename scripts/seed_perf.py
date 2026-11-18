"""Seed a deterministic leaderboard workload and capture MySQL query plans."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import (
    Contest,
    ContestParticipant,
    ContestProblem,
    JudgeAttempt,
    Organization,
    OrganizationMembership,
    Problem,
    ProblemVersion,
    Submission,
    TestCase as DbTestCase,
    TestSuite,
    User,
    Verdict,
)
from app.routers.contests import leaderboard_statement

SEED = 20261118
PARTICIPANTS = 200
PROBLEMS = 3
SUBMISSIONS = 5000
CONTEST_TITLE = "Leaderboard EXPLAIN Perf Seed 2026-11-18"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "explain_leaderboard.txt"


def seed(db):
    existing = db.scalar(select(Contest).where(Contest.title == CONTEST_TITLE).order_by(Contest.id.desc()).limit(1))
    if existing:
        participant_count = db.scalar(select(func.count(ContestParticipant.id)).where(ContestParticipant.contest_id == existing.id))
        problem_count = db.scalar(select(func.count(ContestProblem.id)).where(ContestProblem.contest_id == existing.id))
        submission_count = db.scalar(select(func.count(Submission.id)).where(Submission.contest_id == existing.id))
        if participant_count != PARTICIPANTS or problem_count != PROBLEMS or submission_count != SUBMISSIONS:
            raise RuntimeError(f"Existing perf contest {existing.id} is incomplete; refusing to duplicate seed rows")
        return existing.id, participant_count, problem_count, submission_count

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(hours=4)
    rng = random.Random(SEED)

    owner = User(email="leaderboard-perf-owner@example.test", name="Leaderboard Perf Owner", password_hash="seed-only-not-for-login")
    org = Organization(name="Leaderboard EXPLAIN Perf Organization")
    db.add_all([owner, org])
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner")
    db.add(membership)
    db.flush()

    contest = Contest(
        organization_id=org.id,
        organizer_id=owner.id,
        title=CONTEST_TITLE,
        start_time=start,
        end_time=now + timedelta(days=2),
        status="published",
        scoring_mode="icpc",
        penalty_minutes_per_wrong=20,
    )
    db.add(contest)
    db.flush()

    pins = []
    for index in range(PROBLEMS):
        problem = Problem(organization_id=org.id, title=f"Perf Problem {index + 1}")
        db.add(problem)
        db.flush()
        version = ProblemVersion(
            problem_id=problem.id,
            version_number=1,
            statement=f"Performance fixture problem {index + 1}",
            execution_limits={"time_ms": 1000, "memory_mb": 128},
            runtime_configuration={"python": "3.12"},
            published_at=start,
        )
        db.add(version)
        db.flush()
        suite = TestSuite(problem_version_id=version.id, version_number=1, status="draft")
        db.add(suite)
        db.flush()
        db.add(DbTestCase(test_suite_id=suite.id, identifier="perf-sample", input_data="1\n", expected_output="1\n", is_hidden=False, points=100))
        db.flush()
        suite.status = "active"
        pin = ContestProblem(
            contest_id=contest.id,
            organization_id=org.id,
            problem_id=problem.id,
            problem_version_id=version.id,
            test_suite_id=suite.id,
            display_order=index + 1,
            points=100,
        )
        db.add(pin)
        db.flush()
        pins.append(pin)

    users = [
        User(email=f"leaderboard-perf-{index:03d}@example.test", name=f"Perf Participant {index:03d}", password_hash="seed-only-not-for-login")
        for index in range(PARTICIPANTS)
    ]
    db.add_all(users)
    db.flush()
    participants = [ContestParticipant(contest_id=contest.id, user_id=user.id, status="registered") for user in users]
    db.add_all(participants)
    db.flush()

    submissions = []
    chosen_verdicts = []
    for index in range(SUBMISSIONS):
        participant = participants[rng.randrange(PARTICIPANTS)]
        pin = pins[rng.randrange(PROBLEMS)]
        submitted_at = start + timedelta(seconds=rng.randint(1, 3 * 60 * 60))
        verdict_name = rng.choices(["ACCEPTED", "WRONG_ANSWER", "JUDGE_INFRA_FAILURE"], weights=[25, 60, 15], k=1)[0]
        submission = Submission(
            contest_participant_id=participant.id,
            contest_id=contest.id,
            contest_problem_id=pin.id,
            problem_version_id=pin.problem_version_id,
            test_suite_id=pin.test_suite_id,
            source_code="print(1)\n",
            language="python",
            runtime_config_snapshot={"python": "3.12"},
            status="completed",
            submitted_at=submitted_at,
        )
        submissions.append(submission)
        chosen_verdicts.append(verdict_name)
    db.add_all(submissions)
    db.flush()

    completed_at = now
    attempts = [
        JudgeAttempt(submission_id=submission.id, attempt_number=1, reason="initial", status="completed", completed_at=completed_at)
        for submission in submissions
    ]
    db.add_all(attempts)
    db.flush()

    verdicts = []
    for submission, attempt, verdict_name in zip(submissions, attempts, chosen_verdicts):
        submission.authoritative_attempt_id = attempt.id
        verdicts.append(
            Verdict(
                judge_attempt_id=attempt.id,
                verdict=verdict_name,
                score=100 if verdict_name == "ACCEPTED" else 0,
                execution_time_ms=1,
                memory_used_kb=1024,
                public_message="Seeded performance verdict",
                private_diagnostics=None,
            )
        )
    db.add_all(verdicts)
    db.flush()
    db.commit()
    return contest.id, len(participants), len(pins), len(submissions)


def leaderboard_sql(db, contest_id):
    contest = db.get(Contest, contest_id)
    scored = leaderboard_statement(contest_id, contest).subquery("leaderboard")
    # Mirrors the endpoint's default first page: its scoring SELECT, ranking sort,
    # and limit+1 cursor lookahead, with no cursor or offset supplied.
    statement = (
        select(scored)
        .order_by(
            scored.c.solved.desc(),
            scored.c.penalty.asc(),
            scored.c.last_null.asc(),
            scored.c.last_solved_at.asc(),
            scored.c.participant_id.asc(),
        )
        .limit(51)
    )
    return statement.compile(dialect=db.get_bind().dialect, compile_kwargs={"literal_binds": True})


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"Seed: {SEED}", f"Participants: {PARTICIPANTS}", f"Problems: {PROBLEMS}", f"Submissions: {SUBMISSIONS}"]
    with SessionLocal() as db:
        contest_id, participant_count, problem_count, submission_count = seed(db)
        lines.extend([
            f"Contest ID: {contest_id}",
            f"Seeded participants: {participant_count}",
            f"Seeded problems: {problem_count}",
            f"Seeded submissions with one authoritative completed attempt and verdict each: {submission_count}",
        ])
        sql = str(leaderboard_sql(db, contest_id))
        lines.extend(["", "=== Exact default leaderboard SQL ===", sql, ""])
        connection = db.connection()
        tree = connection.exec_driver_sql("EXPLAIN FORMAT=TREE " + sql).scalar_one()
        analyze = connection.exec_driver_sql("EXPLAIN ANALYZE " + sql).scalar_one()
        lines.extend(["=== EXPLAIN FORMAT=TREE ===", str(tree), "", "=== EXPLAIN ANALYZE ===", str(analyze), ""])

        lines.extend([
            "=== Plan summary ===",
            "Use the raw EXPLAIN FORMAT=TREE and EXPLAIN ANALYZE above for index choices, row estimates, actual rows, scans, sorts and elapsed timings.",
            "This summary intentionally avoids hard-coded estimates and timings so it remains valid when MySQL, indexes or the fixture change.",
            "",
        ])

    output = "\n".join(lines)
    OUTPUT.write_text(output, encoding="utf-8")
    print(output)
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
