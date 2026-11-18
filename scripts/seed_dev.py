"""Idempotently seed LeetCode-style Python function problems and demo contests."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import (
    Contest, ContestParticipant, ContestProblem, JudgeAttempt, Organization,
    OrganizationMembership, Problem, ProblemVersion, Submission, TestCase,
    TestSuite, User,
)

DEMO_PASSWORD = "EasecodingDemo!2026"


def sample_case(identifier, input_data, expected_output, is_hidden=False, points=0):
    return {
        "identifier": identifier,
        "input_data": input_data,
        "expected_output": expected_output,
        "is_hidden": is_hidden,
        "points": points,
    }


PROBLEMS = {
    "Two Number Sum": {
        "function_name": "two_sum",
        "function_driver": "json_args",
        "statement": """Given an integer array nums and an integer target, return the indices of the two values whose sum is target. Exactly one solution exists and an element cannot be used twice.

Input Format: A JSON array [nums, target].
Output Format: A JSON array [i, j] with i < j.
Constraints: 2 <= len(nums) <= 10^4; -10^9 <= nums[i], target <= 10^9; exactly one solution exists.

Example 1:
Input: [[2,7,11,15],9]
Output: [0,1]

Example 2:
Input: [[3,2,4],6]
Output: [1,2]""",
        "program": "def two_sum(nums, target):\n    seen = {}\n    for index, value in enumerate(nums):\n        other = target - value\n        if other in seen:\n            return [seen[other], index]\n        seen[value] = index\n",
        "cases": [
            sample_case("example-1", "[[2,7,11,15],9]", "[0,1]"),
            sample_case("example-2", "[[3,2,4],6]", "[1,2]"),
            sample_case("hidden-1", "[[3,3],6]", "[0,1]", True, 20),
            sample_case("hidden-2", "[[1,5,3,7],10]", "[2,3]", True, 20),
            sample_case("hidden-3", "[[-1,-2,-3,-4,-5],-8]", "[2,4]", True, 20),
            sample_case("hidden-4", "[[0,4,3,0],0]", "[0,3]", True, 20),
            sample_case("hidden-5", "[[10,20,30,40],70]", "[2,3]", True, 20),
        ],
    },
    "String Rotation": {
        "function_name": "is_rotation",
        "function_driver": "json_args",
        "statement": """Return whether string goal is a rotation of string s. A rotation moves a prefix of s to its end without changing character order.

Input Format: A JSON array [s, goal].
Output Format: A JSON boolean.
Constraints: 0 <= len(s), len(goal) <= 10^5; s and goal contain lowercase English letters.

Example 1:
Input: [\"abcde\",\"cdeab\"]
Output: true

Example 2:
Input: [\"abcde\",\"abced\"]
Output: false""",
        "program": "def is_rotation(s, goal):\n    return len(s) == len(goal) and goal in (s + s)\n",
        "cases": [
            sample_case("example-1", '["abcde","cdeab"]', "true"),
            sample_case("example-2", '["abcde","abced"]', "false"),
            sample_case("hidden-1", '[""," "]', "false", True, 20),
            sample_case("hidden-2", '["",""]', "true", True, 20),
            sample_case("hidden-3", '["aaaa","aaaa"]', "true", True, 20),
            sample_case("hidden-4", '["waterbottle","erbottlewat"]', "true", True, 20),
            sample_case("hidden-5", '["rotation","tationro"]', "true", True, 20),
        ],
    },
    "Grid Paths": {
        "function_name": "unique_paths",
        "function_driver": "json_args",
        "statement": """A robot starts at the top-left of an m by n grid and may move only right or down. Return the number of distinct paths to the bottom-right cell.

Input Format: A JSON array [m, n].
Output Format: A JSON integer.
Constraints: 1 <= m, n <= 100.

Example 1:
Input: [3,7]
Output: 28

Example 2:
Input: [3,2]
Output: 3""",
        "program": "from math import comb\n\ndef unique_paths(m, n):\n    return comb(m + n - 2, m - 1)\n",
        "cases": [
            sample_case("example-1", "[3,7]", "28"),
            sample_case("example-2", "[3,2]", "3"),
            sample_case("hidden-1", "[1,1]", "1", True, 20),
            sample_case("hidden-2", "[1,10]", "1", True, 20),
            sample_case("hidden-3", "[10,1]", "1", True, 20),
            sample_case("hidden-4", "[7,3]", "28", True, 20),
            sample_case("hidden-5", "[5,5]", "70", True, 20),
        ],
    },
    "Reverse Linked List": {
        "function_name": "reverse_list",
        "function_driver": "linked_list",
        "statement": """Given the head of a singly linked list, reverse the list and return its new head. Implement reverse_list(head). The judge supplies the ListNode class.

Input Format: A JSON array of node values in list order.
Output Format: A JSON array containing the reversed values.
Constraints: 0 <= number of nodes <= 10^4; -10^5 <= node value <= 10^5.

Example 1:
Input: [1,2,3,4,5]
Output: [5,4,3,2,1]

Example 2:
Input: [1,2]
Output: [2,1]""",
        "program": "def reverse_list(head):\n    previous = None\n    while head is not None:\n        following = head.next\n        head.next = previous\n        previous = head\n        head = following\n    return previous\n",
        "cases": [
            sample_case("example-1", "[1,2,3,4,5]", "[5,4,3,2,1]"),
            sample_case("example-2", "[1,2]", "[2,1]"),
            sample_case("hidden-1", "[]", "[]", True, 20),
            sample_case("hidden-2", "[1]", "[1]", True, 20),
            sample_case("hidden-3", "[1,2,3]", "[3,2,1]", True, 20),
            sample_case("hidden-4", "[-5,0,8]", "[8,0,-5]", True, 20),
            sample_case("hidden-5", "[7,7,7,7]", "[7,7,7,7]", True, 20),
        ],
    },
}

RUNTIME_CONFIGURATIONS = {
    title: {
        "python": "3.12",
        "execution_mode": "function",
        "function_name": spec["function_name"],
        "function_driver": spec["function_driver"],
        "time_limit_seconds": 2.0,
    }
    for title, spec in PROBLEMS.items()
}


def ensure_user(db, email, name):
    row = db.scalar(select(User).where(User.email == email))
    if not row:
        row = User(email=email, name=name, password_hash=hash_password(DEMO_PASSWORD))
        db.add(row)
        db.flush()
    return row


def ensure_membership(db, org, user, role):
    row = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org.id,
        OrganizationMembership.user_id == user.id,
    ))
    if not row:
        db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=role))
    elif row.role != role:
        row.role = role


def cases_match(existing, wanted):
    actual = [
        (row.identifier, row.input_data, row.expected_output, bool(row.is_hidden), row.points)
        for row in existing
    ]
    expected = [
        (row["identifier"], row["input_data"], row["expected_output"], row["is_hidden"], row["points"])
        for row in wanted
    ]
    return actual == expected


def replace_draft_cases(db, suite, wanted):
    existing = list(db.scalars(select(TestCase).where(TestCase.test_suite_id == suite.id).order_by(TestCase.id)))
    by_identifier = {row.identifier: row for row in existing}
    expected_ids = {row["identifier"] for row in wanted}
    for row in existing:
        if row.identifier not in expected_ids:
            db.delete(row)
    for spec in wanted:
        row = by_identifier.get(spec["identifier"])
        if row is None:
            db.add(TestCase(test_suite_id=suite.id, **spec))
        else:
            row.input_data = spec["input_data"]
            row.expected_output = spec["expected_output"]
            row.is_hidden = spec["is_hidden"]
            row.points = spec["points"]
    db.flush()
    suite.status = "active"
    db.flush()


def ensure_problem(db, org, title):
    spec = PROBLEMS[title]
    configuration = RUNTIME_CONFIGURATIONS[title]
    problem = db.scalar(select(Problem).where(Problem.organization_id == org.id, Problem.title == title))
    if not problem:
        problem = Problem(organization_id=org.id, title=title)
        db.add(problem)
        db.flush()

    versions = list(db.scalars(
        select(ProblemVersion).where(ProblemVersion.problem_id == problem.id)
        .order_by(ProblemVersion.version_number.desc())
    ))
    for version in versions:
        if version.statement != spec["statement"] or version.runtime_configuration != configuration:
            continue
        suite = db.scalar(select(TestSuite).where(
            TestSuite.problem_version_id == version.id,
            TestSuite.version_number == 1,
        ))
        if suite and suite.status == "active":
            existing = list(db.scalars(select(TestCase).where(TestCase.test_suite_id == suite.id).order_by(TestCase.id)))
            if cases_match(existing, spec["cases"]):
                return problem, version, suite
            continue
        if suite is None:
            suite = TestSuite(problem_version_id=version.id, version_number=1, status="draft")
            db.add(suite)
            db.flush()
        replace_draft_cases(db, suite, spec["cases"])
        return problem, version, suite

    version_number = max((version.version_number for version in versions), default=0) + 1
    version = ProblemVersion(
        problem_id=problem.id,
        version_number=version_number,
        statement=spec["statement"],
        execution_limits={"time_ms": 2000, "memory_mb": 128},
        runtime_configuration=configuration,
        published_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(version)
    db.flush()
    suite = TestSuite(problem_version_id=version.id, version_number=1, status="draft")
    db.add(suite)
    db.flush()
    for case in spec["cases"]:
        db.add(TestCase(test_suite_id=suite.id, **case))
    db.flush()
    suite.status = "active"
    db.flush()
    return problem, version, suite


def ensure_contest(db, org, organizer, title, pins):
    candidates = list(db.scalars(
        select(Contest).where(Contest.organization_id == org.id, Contest.title == title)
        .order_by(Contest.id.desc())
    ))
    contest = None
    for candidate in candidates:
        exact = True
        for problem, version, suite in pins:
            pin = db.scalar(select(ContestProblem).where(
                ContestProblem.contest_id == candidate.id,
                ContestProblem.problem_id == problem.id,
            ))
            if not pin or (pin.problem_version_id, pin.test_suite_id) != (version.id, suite.id):
                exact = False
                break
        if exact and candidate.status in {"published", "archived"}:
            contest = candidate
            break
    if contest is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        contest = Contest(
            organization_id=org.id,
            organizer_id=organizer.id,
            title=title,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(days=30),
            status="published",
            scoring_mode="icpc",
            penalty_minutes_per_wrong=20,
        )
        db.add(contest)
        db.flush()
        for order, (problem, version, suite) in enumerate(pins, 1):
            db.add(ContestProblem(
                contest_id=contest.id,
                organization_id=org.id,
                problem_id=problem.id,
                problem_version_id=version.id,
                test_suite_id=suite.id,
                display_order=order,
                points=100,
            ))
        db.flush()
    return contest


def ensure_sample_program_submissions(db, contest, participant, pins):
    registration = db.scalar(select(ContestParticipant).where(
        ContestParticipant.contest_id == contest.id,
        ContestParticipant.user_id == participant.id,
    ))
    if not registration:
        registration = ContestParticipant(contest_id=contest.id, user_id=participant.id, status="registered")
        db.add(registration)
        db.flush()
    for problem, version, suite in pins:
        pin = db.scalar(select(ContestProblem).where(
            ContestProblem.contest_id == contest.id,
            ContestProblem.problem_id == problem.id,
        ))
        if db.scalar(select(Submission.id).where(
            Submission.contest_participant_id == registration.id,
            Submission.contest_problem_id == pin.id,
        )):
            continue
        submission = Submission(
            contest_participant_id=registration.id,
            contest_id=contest.id,
            contest_problem_id=pin.id,
            problem_version_id=version.id,
            test_suite_id=suite.id,
            source_code=PROBLEMS[problem.title]["program"],
            language="python",
            runtime_config_snapshot=version.runtime_configuration,
        )
        db.add(submission)
        db.flush()
        db.add(JudgeAttempt(
            submission_id=submission.id,
            attempt_number=1,
            reason="initial",
            requested_by_user_id=participant.id,
            status="queued",
        ))


def main():
    db = SessionLocal()
    try:
        owner = ensure_user(db, "owner@example.test", "Demo Owner")
        organizer = ensure_user(db, "organizer@example.test", "Demo Organizer")
        member = ensure_user(db, "member@example.test", "Demo Member")
        participant = ensure_user(db, "participant@example.test", "Demo Participant")
        org_a = db.scalar(select(Organization).where(Organization.name == "Easecoding Demo Organization A"))
        if not org_a:
            org_a = Organization(name="Easecoding Demo Organization A")
            db.add(org_a)
            db.flush()
        org_b = db.scalar(select(Organization).where(Organization.name == "Easecoding Demo Organization B"))
        if not org_b:
            org_b = Organization(name="Easecoding Demo Organization B")
            db.add(org_b)
            db.flush()
        ensure_membership(db, org_a, owner, "owner")
        ensure_membership(db, org_a, organizer, "organizer")
        ensure_membership(db, org_a, member, "member")
        ensure_membership(db, org_b, member, "owner")

        a1 = ensure_problem(db, org_a, "Two Number Sum")
        a2 = ensure_problem(db, org_a, "String Rotation")
        b1 = ensure_problem(db, org_b, "Grid Paths")
        b2 = ensure_problem(db, org_b, "Reverse Linked List")
        contest_a = ensure_contest(db, org_a, organizer, "Easecoding Demo Contest A", [a1, a2])
        contest_b = ensure_contest(db, org_b, member, "Easecoding Demo Contest B", [b1, b2])
        ensure_sample_program_submissions(db, contest_a, participant, [a1, a2])
        ensure_sample_program_submissions(db, contest_b, participant, [b1, b2])
        db.commit()
        print(
            f"Seeded function-style contests A={contest_a.id} and B={contest_b.id}; "
            "4 problems, 4 sample programs, 2 visible examples and 5 hidden cases per problem."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
