"""Database-level membership protections; no HTTP requests are made here."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal
from app.main import db_error_handler
from app.models import Contest, Organization, OrganizationMembership, User


def create_membership(db, role):
    suffix = uuid4().hex
    user = User(email=f"trigger-{suffix}@example.test", name="Trigger Test", password_hash="unused")
    org = Organization(name=f"trigger-org-{suffix}")
    db.add_all([user, org])
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role=role)
    db.add(membership)
    db.commit()
    return org.id, user.id, membership.id


def create_organizer_contest(db):
    suffix = uuid4().hex
    owner = User(email=f"trigger-owner-{suffix}@example.test", name="Owner", password_hash="unused")
    organizer = User(email=f"trigger-organizer-{suffix}@example.test", name="Organizer", password_hash="unused")
    org = Organization(name=f"organizer-org-{suffix}")
    db.add_all([owner, organizer, org])
    db.flush()
    owner_membership = OrganizationMembership(organization_id=org.id, user_id=owner.id, role="owner")
    organizer_membership = OrganizationMembership(organization_id=org.id, user_id=organizer.id, role="organizer")
    db.add_all([owner_membership, organizer_membership])
    db.flush()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    contest = Contest(
        organization_id=org.id,
        organizer_id=organizer.id,
        title=f"Organizer Trigger Test {suffix}",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        status="draft",
    )
    db.add(contest)
    db.commit()
    return org.id, organizer.id, organizer_membership.id, contest.id


def assert_trigger_error(exc, expected_code):
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "sql_state", None)
    assert sqlstate == "45000", f"expected SQLSTATE 45000, got {sqlstate!r}: {orig!r}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/test/membership-trigger",
        "raw_path": b"/test/membership-trigger",
        "query_string": b"",
        "headers": [],
        "client": ("test", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    request.state.request_id = "membership-trigger-test"
    response = asyncio.run(db_error_handler(request, exc))
    payload = json.loads(response.body)
    assert response.status_code == 409
    assert payload["error"]["code"] == expected_code


def run_raw_and_expect_error(db, sql, params, expected_code):
    try:
        db.execute(text(sql), params)
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        assert_trigger_error(exc, expected_code)
    else:
        pytest.fail(f"database trigger did not reject statement for {expected_code}")


def test_raw_sql_demoting_only_owner_is_sqlstate_45000_and_maps_409():
    with SessionLocal() as db:
        org_id, user_id, membership_id = create_membership(db, "owner")
        run_raw_and_expect_error(
            db,
            "UPDATE organization_memberships SET role='member' WHERE id=:membership_id",
            {"membership_id": membership_id},
            "LAST_OWNER_REQUIRED",
        )
        assert db.scalar(select(OrganizationMembership.role).where(OrganizationMembership.id == membership_id)) == "owner"


def test_raw_sql_deleting_only_owner_is_sqlstate_45000_and_maps_409():
    with SessionLocal() as db:
        org_id, user_id, membership_id = create_membership(db, "owner")
        run_raw_and_expect_error(
            db,
            "DELETE FROM organization_memberships WHERE id=:membership_id",
            {"membership_id": membership_id},
            "LAST_OWNER_REQUIRED",
        )
        assert db.scalar(select(OrganizationMembership.id).where(OrganizationMembership.id == membership_id)) == membership_id


def test_raw_sql_demoting_organizer_of_draft_contest_is_guarded():
    with SessionLocal() as db:
        org_id, organizer_id, membership_id, contest_id = create_organizer_contest(db)
        run_raw_and_expect_error(
            db,
            "UPDATE organization_memberships SET role='member' WHERE id=:membership_id",
            {"membership_id": membership_id},
            "MEMBER_IS_CONTEST_ORGANIZER",
        )
        assert db.scalar(select(OrganizationMembership.role).where(OrganizationMembership.id == membership_id)) == "organizer"


def test_raw_sql_organizer_demotion_succeeds_after_contest_archived():
    with SessionLocal() as db:
        org_id, organizer_id, membership_id, contest_id = create_organizer_contest(db)
        run_raw_and_expect_error(
            db,
            "UPDATE organization_memberships SET role='member' WHERE id=:membership_id",
            {"membership_id": membership_id},
            "MEMBER_IS_CONTEST_ORGANIZER",
        )
        db.execute(text("UPDATE contests SET status='archived' WHERE id=:contest_id"), {"contest_id": contest_id})
        db.commit()
        db.execute(text("UPDATE organization_memberships SET role='member' WHERE id=:membership_id"), {"membership_id": membership_id})
        db.commit()
        assert db.scalar(select(OrganizationMembership.role).where(OrganizationMembership.id == membership_id)) == "member"
