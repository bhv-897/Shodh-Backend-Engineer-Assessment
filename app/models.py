from datetime import datetime
from sqlalchemy import (String, Text, Integer, BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, JSON, Index, func)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from app.db import Base

class User(Base):
    __tablename__="users"
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str]=mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str]=mapped_column(String(160), nullable=False)
    password_hash: Mapped[str]=mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class Organization(Base):
    __tablename__="organizations"
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str]=mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class OrganizationMembership(Base):
    __tablename__="organization_memberships"
    __table_args__=(UniqueConstraint("organization_id","user_id"), CheckConstraint("role IN ('owner','organizer','member')"),Index("ix_memberships_user_org","user_id","organization_id"),Index("ix_memberships_org_id","organization_id","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int]=mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[int]=mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str]=mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class Problem(Base):
    __tablename__="problems"
    __table_args__=(UniqueConstraint("id","organization_id"),Index("ix_problems_org_id","organization_id","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int]=mapped_column(ForeignKey("organizations.id"), nullable=False)
    title: Mapped[str]=mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class ProblemVersion(Base):
    __tablename__="problem_versions"
    __table_args__=(UniqueConstraint("problem_id","version_number"),UniqueConstraint("id","problem_id"),Index("ix_problem_versions_problem_published","problem_id","published_at","version_number"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    problem_id: Mapped[int]=mapped_column(ForeignKey("problems.id"), nullable=False)
    version_number: Mapped[int]=mapped_column(Integer, nullable=False)
    statement: Mapped[str]=mapped_column(Text, nullable=False)
    execution_limits: Mapped[dict]=mapped_column(JSON, nullable=False)
    runtime_configuration: Mapped[dict]=mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime|None]=mapped_column(DateTime(6))
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class TestSuite(Base):
    __tablename__="test_suites"
    __table_args__=(UniqueConstraint("problem_version_id","version_number"),UniqueConstraint("id","problem_version_id"),CheckConstraint("status IN ('draft','active','retired')"),Index("ix_test_suites_version_status","problem_version_id","status","version_number"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    problem_version_id: Mapped[int]=mapped_column(ForeignKey("problem_versions.id"), nullable=False)
    version_number: Mapped[int]=mapped_column(Integer, nullable=False)
    status: Mapped[str]=mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class TestCase(Base):
    __tablename__="test_cases"
    __table_args__=(UniqueConstraint("test_suite_id","identifier"),CheckConstraint("points >= 0"),Index("ix_test_cases_suite_id","test_suite_id","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    test_suite_id: Mapped[int]=mapped_column(ForeignKey("test_suites.id"), nullable=False)
    identifier: Mapped[str]=mapped_column(String(100), nullable=False)
    input_data: Mapped[str]=mapped_column(Text, nullable=False)
    expected_output: Mapped[str]=mapped_column(Text, nullable=False)
    is_hidden: Mapped[bool]=mapped_column(Boolean, nullable=False, server_default="0")
    points: Mapped[int]=mapped_column(Integer, nullable=False, server_default="0")

class Contest(Base):
    __tablename__="contests"
    __table_args__=(UniqueConstraint("id","organization_id"),ForeignKeyConstraint(["organization_id","organizer_id"],["organization_memberships.organization_id","organization_memberships.user_id"]),CheckConstraint("end_time > start_time"),Index("ix_contests_org_status_id","organization_id","status","id"),Index("ix_contests_status_start_id","status","start_time","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int]=mapped_column(ForeignKey("organizations.id"), nullable=False)
    organizer_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    title: Mapped[str]=mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime]=mapped_column(DateTime(6), nullable=False)
    end_time: Mapped[datetime]=mapped_column(DateTime(6), nullable=False)
    status: Mapped[str]=mapped_column(String(16), nullable=False, server_default="draft")
    scoring_mode: Mapped[str]=mapped_column(String(32), nullable=False, server_default="icpc")
    penalty_minutes_per_wrong: Mapped[int]=mapped_column(Integer, nullable=False, server_default="20")
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class ContestParticipant(Base):
    __tablename__="contest_participants"
    __table_args__=(UniqueConstraint("contest_id","user_id"),UniqueConstraint("id","contest_id"),CheckConstraint("status IN ('registered','withdrawn','disqualified')"),Index("ix_participants_contest_status_registered","contest_id","status","registered_at","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contest_id: Mapped[int]=mapped_column(ForeignKey("contests.id"), nullable=False)
    user_id: Mapped[int]=mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str]=mapped_column(String(20), nullable=False, server_default="registered")
    registered_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class ContestProblem(Base):
    __tablename__="contest_problems"
    __table_args__=(UniqueConstraint("contest_id","problem_id"),UniqueConstraint("contest_id","display_order"),UniqueConstraint("id","contest_id","problem_version_id","test_suite_id"),ForeignKeyConstraint(["contest_id","organization_id"],["contests.id","contests.organization_id"]),ForeignKeyConstraint(["problem_id","organization_id"],["problems.id","problems.organization_id"]),ForeignKeyConstraint(["problem_version_id","problem_id"],["problem_versions.id","problem_versions.problem_id"]),ForeignKeyConstraint(["test_suite_id","problem_version_id"],["test_suites.id","test_suites.problem_version_id"]),Index("ix_contest_problems_contest_order","contest_id","display_order","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contest_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    organization_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    problem_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    problem_version_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    test_suite_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    display_order: Mapped[int]=mapped_column(Integer, nullable=False)
    points: Mapped[int]=mapped_column(Integer, nullable=False)

class Submission(Base):
    __tablename__="submissions"
    __table_args__=(ForeignKeyConstraint(["contest_participant_id","contest_id"],["contest_participants.id","contest_participants.contest_id"]),ForeignKeyConstraint(["contest_problem_id","contest_id","problem_version_id","test_suite_id"],["contest_problems.id","contest_problems.contest_id","contest_problems.problem_version_id","contest_problems.test_suite_id"]),UniqueConstraint("id","contest_id"),Index("ix_submissions_contest_submitted_id","contest_id","submitted_at","id"),Index("ix_submissions_participant_problem_submitted","contest_participant_id","contest_problem_id","submitted_at","id"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contest_participant_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    contest_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    contest_problem_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    problem_version_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    test_suite_id: Mapped[int]=mapped_column(BigInteger, nullable=False)
    source_code: Mapped[str]=mapped_column(MEDIUMTEXT, nullable=False)
    language: Mapped[str]=mapped_column(String(32), nullable=False)
    runtime_config_snapshot: Mapped[dict]=mapped_column(JSON, nullable=False)
    status: Mapped[str]=mapped_column(String(20), nullable=False, server_default="queued")
    authoritative_attempt_id: Mapped[int|None]=mapped_column(BigInteger)
    submitted_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class JudgeAttempt(Base):
    __tablename__="judge_attempts"
    __table_args__=(UniqueConstraint("submission_id","attempt_number"),UniqueConstraint("id","submission_id"),CheckConstraint("reason IN ('initial','rejudge')"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int]=mapped_column(ForeignKey("submissions.id"), nullable=False)
    attempt_number: Mapped[int]=mapped_column(Integer, nullable=False)
    reason: Mapped[str]=mapped_column(String(16), nullable=False)
    requested_by_user_id: Mapped[int|None]=mapped_column(ForeignKey("users.id"))
    status: Mapped[str]=mapped_column(String(16), nullable=False, server_default="queued")
    worker_id: Mapped[str|None]=mapped_column(String(128))
    lease_token: Mapped[str|None]=mapped_column(String(128))
    lease_expires_at: Mapped[datetime|None]=mapped_column(DateTime(6))
    retry_count: Mapped[int]=mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime|None]=mapped_column(DateTime(6))
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(6))
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

class Verdict(Base):
    __tablename__="verdicts"
    __table_args__=(UniqueConstraint("judge_attempt_id"),CheckConstraint("verdict IN ('ACCEPTED','WRONG_ANSWER','COMPILATION_ERROR','TIME_LIMIT_EXCEEDED','MEMORY_LIMIT_EXCEEDED','RUNTIME_ERROR','JUDGE_INFRA_FAILURE')"),CheckConstraint("score >= 0"))
    id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    judge_attempt_id: Mapped[int]=mapped_column(ForeignKey("judge_attempts.id"), nullable=False)
    verdict: Mapped[str]=mapped_column(String(32), nullable=False)
    score: Mapped[int]=mapped_column(Integer, nullable=False, server_default="0")
    execution_time_ms: Mapped[int|None]=mapped_column(Integer)
    memory_used_kb: Mapped[int|None]=mapped_column(Integer)
    public_message: Mapped[str|None]=mapped_column(Text)
    private_diagnostics: Mapped[str|None]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(6), server_default=func.utc_timestamp(6), nullable=False)

# Added after judge_attempts exists in migration 0001 (intentional circular reference).
