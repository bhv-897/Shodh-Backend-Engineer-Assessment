"""Minimal polling judge worker: ``python -m app.worker``."""
from __future__ import annotations

import logging
import os
import socket
import argparse
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, case, exists, or_, select, update

from app.db import SessionLocal
from app.judge_runner import DockerPythonRunner, judge_submission
from app.logging_config import configure_json_logging
from app.models import JudgeAttempt, OutboxEvent, Submission, TestCase
from app.services.verdicts import record_verdict

configure_json_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("app.worker")
POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "1"))
LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "300"))
MAX_RETRIES = int(os.getenv("WORKER_MAX_RETRIES", "3"))


def process_one(runner=None, event_id: int | None = None) -> bool:
    lease_token = str(uuid4())
    worker_id = socket.gethostname()
    event_data = None
    with SessionLocal() as db:
        with db.begin():
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            expired_running = exists(
                select(JudgeAttempt.id).where(
                    JudgeAttempt.id == OutboxEvent.judge_attempt_id,
                    JudgeAttempt.status == "running",
                    JudgeAttempt.lease_expires_at <= now,
                )
            )
            completed_attempt = exists(
                select(JudgeAttempt.id).where(
                    JudgeAttempt.id == OutboxEvent.judge_attempt_id,
                    JudgeAttempt.status == "completed",
                )
            )
            query = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "judge.requested",
                    or_(
                        OutboxEvent.status == "pending",
                        and_(OutboxEvent.status == "processing", or_(expired_running, completed_attempt)),
                    ),
                )
                .order_by(OutboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if event_id is not None:
                query = query.where(OutboxEvent.id == event_id)
            event = db.scalar(query)
            if event is None:
                return False
            attempt = db.scalar(select(JudgeAttempt).where(JudgeAttempt.id == event.judge_attempt_id).with_for_update())
            if event.status == "processing" and attempt.status == "completed":
                event.status = "published"
                event.published_at = now
                return True
            retry_exhausted = False
            previous_lease_token = None
            if event.status == "processing":
                retry_exhausted = attempt.retry_count >= MAX_RETRIES
                previous_lease_token = attempt.lease_token
                conditions = (
                    JudgeAttempt.id == attempt.id,
                    JudgeAttempt.status == "running",
                    JudgeAttempt.lease_expires_at <= now,
                )
                claimed = db.execute(
                    update(JudgeAttempt).where(*conditions).values(
                        worker_id=worker_id,
                        lease_token=lease_token,
                        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                        retry_count=case((JudgeAttempt.retry_count < MAX_RETRIES, JudgeAttempt.retry_count + 1), else_=JudgeAttempt.retry_count),
                    )
                )
            else:
                if attempt.status == "completed":
                    event.status = "published"
                    event.published_at = now
                    return True
                claimed = db.execute(
                    update(JudgeAttempt)
                    .where(JudgeAttempt.id == attempt.id, JudgeAttempt.status == "queued")
                    .values(
                        status="running",
                        worker_id=worker_id,
                        lease_token=lease_token,
                        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                        started_at=now,
                    )
                )
            if claimed.rowcount != 1:
                return False
            event.status = "processing"
            submission = db.get(Submission, attempt.submission_id)
            cases = [] if retry_exhausted else list(
                    db.scalars(select(TestCase).where(TestCase.test_suite_id == submission.test_suite_id).order_by(TestCase.id))
                )
            event_data = {
                "event_id": event.id,
                "attempt_id": attempt.id,
                "submission_id": submission.id,
                "source_code": submission.source_code,
                "runtime_configuration": submission.runtime_config_snapshot or {},
                "timeout_seconds": float(submission.runtime_config_snapshot.get("time_limit_seconds", 2.0)),
                "retry_exhausted": retry_exhausted,
                "previous_lease_token": previous_lease_token,
                "cases": [
                    {"id": case.id, "input_data": case.input_data, "expected_output": case.expected_output, "is_hidden": case.is_hidden}
                    for case in cases
                ],
            }

    verdict = "JUDGE_INFRA_FAILURE"
    score = 0
    execution_time_ms = None
    public_message = "The judge could not complete this submission. Please contact the contest organizer."
    diagnostics = None
    case_results = []
    try:
        active_runner = runner or DockerPythonRunner(attempt_id=event_data["attempt_id"], lease_token=lease_token)
        if event_data["previous_lease_token"] and hasattr(active_runner, "cleanup_lease"):
            active_runner.cleanup_lease(event_data["attempt_id"], event_data["previous_lease_token"])
        if event_data["retry_exhausted"]:
            raise RuntimeError("Judge attempt exceeded the bounded recovery retry limit")
        if not event_data["cases"]:
            raise RuntimeError("Pinned test suite has no test cases")
        verdict, score, execution_time_ms, public_message, diagnostics, case_results = judge_submission(
            active_runner,
            event_data["source_code"],
            event_data["cases"],
            event_data["timeout_seconds"],
            event_data["runtime_configuration"],
        )
    except Exception as exc:  # worker and Docker failures are judge infrastructure failures
        diagnostics = f"{type(exc).__name__}: {exc}"

    with SessionLocal() as db:
        record_verdict(
            db,
            event_data["attempt_id"],
            verdict,
            score=score,
            execution_time_ms=execution_time_ms,
            public_message=public_message,
            private_diagnostics=diagnostics,
            lease_token=lease_token,
            case_results=case_results,
        )
        with db.begin():
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_data["event_id"]).with_for_update())
            event.status = "published"
            event.published_at = datetime.now(timezone.utc).replace(tzinfo=None)
    logger.info("Judge attempt completed", extra={
        "event": "judge.attempt.completed",
        "request_id": None,
        "submission_id": event_data["submission_id"],
        "attempt_id": event_data["attempt_id"],
        "verdict": verdict,
    })
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="process at most one outbox event and exit")
    parser.add_argument("--event-id", type=int, help="restrict one-shot processing to a single event")
    args = parser.parse_args()
    if args.once:
        try:
            process_one(event_id=args.event_id)
            return 0
        except Exception:
            logger.error("One-shot judge worker failed")
            return 1
    logger.info("Judge worker started", extra={
        "event": "judge.worker.started", "request_id": None,
        "submission_id": None, "attempt_id": None,
    })
    while True:
        try:
            if not process_one():
                time.sleep(POLL_SECONDS)
        except Exception:
            # Do not include submission data, testcase content, stderr, or diagnostics in logs.
            logger.error("Judge worker iteration failed", extra={
                "event": "judge.worker.failure", "request_id": None,
                "submission_id": None, "attempt_id": None,
            })
            time.sleep(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
