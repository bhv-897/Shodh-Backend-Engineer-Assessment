"""Idempotent Swagger data. Run after migrations: python -m scripts.seed_dev"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db import SessionLocal
from app.auth import hash_password
from app.models import (User, Organization, OrganizationMembership, Problem, ProblemVersion,
                        TestSuite, TestCase, Contest, ContestProblem, ContestParticipant,
                        Submission, JudgeAttempt)

DEMO_PASSWORD="EasecodingDemo!2026"
SAMPLE_PROGRAMS={
    "Two Number Sum":"import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)\n",
    "String Rotation":"a = input().strip()\nb = input().strip()\nprint('YES' if len(a) == len(b) and b in a + a else 'NO')\n",
    "Grid Paths":"from math import comb\nn, m = map(int, input().split())\nprint(comb(n + m - 2, n - 1))\n",
}

def ensure_user(db,email,name):
    row=db.scalar(select(User).where(User.email==email))
    if not row:
        row=User(email=email,name=name,password_hash=hash_password(DEMO_PASSWORD)); db.add(row); db.flush()
    return row

def ensure_membership(db,org,user,role):
    row=db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==org.id,OrganizationMembership.user_id==user.id))
    if not row: db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role=role))
    elif row.role!=role: row.role=role

def ensure_problem(db,org,title):
    problem=db.scalar(select(Problem).where(Problem.organization_id==org.id,Problem.title==title))
    if not problem:
        problem=Problem(organization_id=org.id,title=title); db.add(problem); db.flush()
    version=db.scalar(select(ProblemVersion).where(ProblemVersion.problem_id==problem.id,ProblemVersion.version_number==1))
    if not version:
        version=ProblemVersion(problem_id=problem.id,version_number=1,statement=f"Solve: {title}",execution_limits={"time_ms":1000,"memory_mb":256},runtime_configuration={"python":"3.12"},published_at=datetime.now(timezone.utc).replace(tzinfo=None)); db.add(version); db.flush()
    suite=db.scalar(select(TestSuite).where(TestSuite.problem_version_id==version.id,TestSuite.version_number==1))
    if not suite:
        suite=TestSuite(problem_version_id=version.id,version_number=1,status="draft"); db.add(suite); db.flush()
    if not db.scalar(select(TestCase.id).where(TestCase.test_suite_id==suite.id)):
        db.add(TestCase(test_suite_id=suite.id,identifier="sample-1",input_data="2 3\n",expected_output="5\n",is_hidden=False,points=100))
        db.flush()
    if suite.status!="active": suite.status="active"
    return problem,version,suite

def ensure_contest(db,org,organizer,title,pins):
    contest=db.scalar(select(Contest).where(Contest.organization_id==org.id,Contest.title==title))
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    if not contest:
        contest=Contest(organization_id=org.id,organizer_id=organizer.id,title=title,start_time=now-timedelta(hours=1),end_time=now+timedelta(days=30),status="draft",scoring_mode="icpc",penalty_minutes_per_wrong=20)
        db.add(contest); db.flush()
    for order,(problem,version,suite) in enumerate(pins,1):
        if not db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id==contest.id,ContestProblem.problem_id==problem.id)):
            db.add(ContestProblem(contest_id=contest.id,organization_id=org.id,problem_id=problem.id,problem_version_id=version.id,test_suite_id=suite.id,display_order=order,points=100))
    db.flush()
    if contest.status=="draft": contest.status="published"
    return contest

def ensure_sample_program_submissions(db,contest,participant,pins):
    registration=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==contest.id,ContestParticipant.user_id==participant.id))
    if not registration:
        registration=ContestParticipant(contest_id=contest.id,user_id=participant.id,status="registered"); db.add(registration); db.flush()
    for problem,version,suite in pins:
        pin=db.scalar(select(ContestProblem).where(ContestProblem.contest_id==contest.id,ContestProblem.problem_id==problem.id))
        if db.scalar(select(Submission.id).where(Submission.contest_participant_id==registration.id,Submission.contest_problem_id==pin.id)):
            continue
        submission=Submission(contest_participant_id=registration.id,contest_id=contest.id,contest_problem_id=pin.id,problem_version_id=version.id,test_suite_id=suite.id,source_code=SAMPLE_PROGRAMS[problem.title],language="python",runtime_config_snapshot=version.runtime_configuration)
        db.add(submission); db.flush()
        db.add(JudgeAttempt(submission_id=submission.id,attempt_number=1,reason="initial",requested_by_user_id=participant.id,status="queued"))

def main():
    db=SessionLocal()
    try:
        owner=ensure_user(db,"owner@example.test","Demo Owner")
        organizer=ensure_user(db,"organizer@example.test","Demo Organizer")
        member=ensure_user(db,"member@example.test","Demo Member")
        participant=ensure_user(db,"participant@example.test","Demo Participant")
        org_a=db.scalar(select(Organization).where(Organization.name=="Easecoding Demo Organization A"))
        if not org_a: org_a=Organization(name="Easecoding Demo Organization A"); db.add(org_a); db.flush()
        org_b=db.scalar(select(Organization).where(Organization.name=="Easecoding Demo Organization B"))
        if not org_b: org_b=Organization(name="Easecoding Demo Organization B"); db.add(org_b); db.flush()
        ensure_membership(db,org_a,owner,"owner"); ensure_membership(db,org_a,organizer,"organizer"); ensure_membership(db,org_a,member,"member")
        ensure_membership(db,org_b,member,"owner")
        a1=ensure_problem(db,org_a,"Two Number Sum"); a2=ensure_problem(db,org_a,"String Rotation"); b1=ensure_problem(db,org_b,"Grid Paths")
        contest_a=ensure_contest(db,org_a,organizer,"Easecoding Demo Contest A",[a1,a2])
        contest_b=ensure_contest(db,org_b,member,"Easecoding Demo Contest B",[b1])
        ensure_sample_program_submissions(db,contest_a,participant,[a1,a2])
        ensure_sample_program_submissions(db,contest_b,participant,[b1])
        db.commit()
        print(f"Seeded 4 users, 2 organizations, 2 contests, 3 problems, and 3 queued Python sample submissions. Password: {DEMO_PASSWORD}")
    except Exception:
        db.rollback(); raise
    finally: db.close()

if __name__=="__main__": main()
