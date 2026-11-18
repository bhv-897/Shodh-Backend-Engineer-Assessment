from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import SessionLocal
from app.models import (User, Organization, OrganizationMembership, Contest, Problem,
                        ProblemVersion, TestSuite as DbTestSuite, ContestProblem, ContestParticipant,
                        Submission, JudgeAttempt)
from app.routers.contests import leaderboard_statement
from app.services.verdicts import record_verdict

PASSWORD="Strong-Test-Password-2026"

def new_user(client,name):
    email=f"{name}-{uuid4().hex}@example.test"
    r=client.post("/api/v1/auth/register",json={"name":name,"email":email,"password":PASSWORD})
    assert r.status_code==201, r.text
    token=client.post("/api/v1/auth/login",json={"email":email,"password":PASSWORD}).json()["access_token"]
    return email,{"Authorization":f"Bearer {token}"}

def test_org_scope_role_and_draft_pin_visibility(client):
    _,owner=new_user(client,"owner")
    email,member=new_user(client,"member")
    _,stranger=new_user(client,"stranger")
    org=client.post("/api/v1/organizations",headers=owner,json={"name":f"org-{uuid4().hex}"}).json()
    oid=org["id"]
    assert client.post(f"/api/v1/organizations/{oid}/members",headers=owner,json={"email":email,"role":"member"}).status_code==201
    assert client.get(f"/api/v1/organizations/{oid}",headers=stranger).status_code==404
    assert client.post(f"/api/v1/organizations/{oid}/problems",headers=member,json={"title":"forbidden"}).status_code==403

    start=datetime.now(timezone.utc)+timedelta(hours=1)
    end=start+timedelta(hours=2)
    contest=client.post(f"/api/v1/organizations/{oid}/contests",headers=owner,json={"title":"private draft","start_time":start.isoformat(),"end_time":end.isoformat()})
    assert contest.status_code==201, contest.text
    cid=contest.json()["id"]
    assert client.get(f"/api/v1/contests/{cid}/problems",headers=stranger).status_code==404
    assert client.get(f"/api/v1/contests/{cid}/problems/123",headers=stranger).status_code==404

def test_database_triggers_guard_published_version_active_suite_and_membership(client):
    owner_email,owner=new_user(client,"trigger-owner")
    organizer_email,organizer=new_user(client,"trigger-organizer")
    org=client.post("/api/v1/organizations",headers=owner,json={"name":f"trigger-org-{uuid4().hex}"}).json()
    oid=org["id"]
    assert client.post(f"/api/v1/organizations/{oid}/members",headers=owner,json={"email":organizer_email,"role":"organizer"}).status_code==201
    problem=client.post(f"/api/v1/organizations/{oid}/problems",headers=organizer,json={"title":"trigger problem"}).json()
    version=client.post(f"/api/v1/problems/{problem['id']}/versions",headers=organizer,json={"statement":"s","execution_limits":{},"runtime_configuration":{}}).json()
    assert client.post(f"/api/v1/problem-versions/{version['id']}/publish",headers=organizer).status_code==200
    suite=client.post(f"/api/v1/problem-versions/{version['id']}/test-suites",headers=organizer).json()
    assert client.post(f"/api/v1/test-suites/{suite['id']}/test-cases",headers=organizer,json={"identifier":"one","input_data":"1","expected_output":"1","points":1}).status_code==201
    assert client.post(f"/api/v1/test-suites/{suite['id']}/activate",headers=organizer).status_code==200

    with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE organization_memberships SET role='member' WHERE organization_id=:oid AND user_id=(SELECT id FROM users WHERE email=:email)"),{"oid":oid,"email":owner_email})
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE problem_versions SET statement='mutated' WHERE id=:id"),{"id":version["id"]})
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(text("INSERT INTO test_cases(test_suite_id,identifier,input_data,expected_output,is_hidden,points) VALUES (:sid,'blocked','i','o',0,0)"),{"sid":suite["id"]})
            db.commit()
        db.rollback()

    now=datetime.now(timezone.utc)
    c=client.post(f"/api/v1/organizations/{oid}/contests",headers=organizer,json={"title":"organizer lock","start_time":(now+timedelta(hours=1)).isoformat(),"end_time":(now+timedelta(hours=2)).isoformat()})
    assert c.status_code==201, c.text
    with SessionLocal() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE organization_memberships SET role='member' WHERE organization_id=:oid AND user_id=(SELECT id FROM users WHERE email=:email)"),{"oid":oid,"email":organizer_email})
            db.commit()
        db.rollback()

def test_infra_verdict_does_not_replace_authoritative_attempt(client):
    email,_=new_user(client,"verdict-owner")
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email))
        org=Organization(name=f"verdict-org-{uuid4().hex}"); db.add(org); db.flush()
        db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role="owner")); db.flush()
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        contest=Contest(organization_id=org.id,organizer_id=user.id,title="verdict contest",start_time=now-timedelta(hours=1),end_time=now+timedelta(hours=1),status="published"); db.add(contest); db.flush()
        problem=Problem(organization_id=org.id,title="verdict problem"); db.add(problem); db.flush()
        version=ProblemVersion(problem_id=problem.id,version_number=1,statement="s",execution_limits={},runtime_configuration={},published_at=now); db.add(version); db.flush()
        suite=DbTestSuite(problem_version_id=version.id,version_number=1,status="active"); db.add(suite); db.flush()
        pin=ContestProblem(contest_id=contest.id,organization_id=org.id,problem_id=problem.id,problem_version_id=version.id,test_suite_id=suite.id,display_order=1,points=100); db.add(pin); db.flush()
        participant=ContestParticipant(contest_id=contest.id,user_id=user.id,status="registered"); db.add(participant); db.flush()
        submission=Submission(contest_participant_id=participant.id,contest_id=contest.id,contest_problem_id=pin.id,problem_version_id=version.id,test_suite_id=suite.id,source_code="print(1)",language="python",runtime_config_snapshot={}); db.add(submission); db.flush()
        attempts=[JudgeAttempt(submission_id=submission.id,attempt_number=n,reason="initial",status="queued") for n in (1,2,3,4)]
        db.add_all(attempts); db.commit(); submission_id=submission.id; older_id,newer_id,infra_id=[a.id for a in attempts[:3]]

    for attempt_id,verdict,score in ((newer_id,"ACCEPTED",100),(infra_id,"JUDGE_INFRA_FAILURE",0),(older_id,"WRONG_ANSWER",0)):
        with SessionLocal() as db:
            record_verdict(db,attempt_id,verdict,score=score)
    with SessionLocal() as db:
        saved=db.get(Submission,submission_id)
        assert saved.authoritative_attempt_id==newer_id
        assert saved.status=="completed"
        compilation_id=attempts[3].id
    with SessionLocal() as db:
        record_verdict(db,compilation_id,"COMPILATION_ERROR")
    with SessionLocal() as db:
        assert db.get(Submission,submission_id).authoritative_attempt_id==compilation_id

def make_contest_graph(db,user,title):
    org=Organization(name=f"{title}-{uuid4().hex}"); db.add(org); db.flush()
    db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role="owner")); db.flush()
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    contest=Contest(organization_id=org.id,organizer_id=user.id,title=title,start_time=now-timedelta(minutes=60),end_time=now+timedelta(hours=2),status="published"); db.add(contest); db.flush()
    problem=Problem(organization_id=org.id,title=title); db.add(problem); db.flush()
    version=ProblemVersion(problem_id=problem.id,version_number=1,statement="s",execution_limits={},runtime_configuration={},published_at=now); db.add(version); db.flush()
    suite=DbTestSuite(problem_version_id=version.id,version_number=1,status="active"); db.add(suite); db.flush()
    pin=ContestProblem(contest_id=contest.id,organization_id=org.id,problem_id=problem.id,problem_version_id=version.id,test_suite_id=suite.id,display_order=1,points=100); db.add(pin); db.flush()
    return contest,pin,now

def test_submission_window_registration_and_private_submission_access(client):
    _,organizer_headers=new_user(client,"window-organizer")
    _,user_a_headers=new_user(client,"participant-a")
    _,user_b_headers=new_user(client,"participant-b")
    _,unregistered_headers=new_user(client,"unregistered")
    org=client.post("/api/v1/organizations",headers=organizer_headers,json={"name":f"window-org-{uuid4().hex}"}).json()
    owner_id=client.get("/api/v1/auth/me",headers=organizer_headers).json()["id"]
    with SessionLocal() as db:
        owner=db.get(User,owner_id)
        contest,pin,now=make_contest_graph(db,owner,"window contest")
        contest_id,pin_id=contest.id,pin.id
        db.commit()
    # Move just outside the opening window and verify the conflict before registration.
    with SessionLocal.begin() as db:
        db.execute(text("UPDATE contests SET start_time=:start WHERE id=:id"),{"start":now+timedelta(minutes=1),"id":contest_id})
    assert client.post(f"/api/v1/contests/{contest_id}/problems/{pin_id}/submissions",headers=unregistered_headers,json={"source_code":"print(1)","language":"python"}).json()["error"]["code"]=="CONTEST_NOT_OPEN"
    with SessionLocal.begin() as db:
        db.execute(text("UPDATE contests SET start_time=:start WHERE id=:id"),{"start":now-timedelta(minutes=60),"id":contest_id})
    denied=client.post(f"/api/v1/contests/{contest_id}/problems/{pin_id}/submissions",headers=unregistered_headers,json={"source_code":"print(1)","language":"python"})
    assert denied.status_code==403 and denied.json()["error"]["code"]=="NOT_REGISTERED"
    assert client.post(f"/api/v1/contests/{contest_id}/register",headers=user_a_headers).status_code==201
    submission=client.post(f"/api/v1/contests/{contest_id}/problems/{pin_id}/submissions",headers=user_a_headers,json={"source_code":"print(1)","language":"python"})
    assert submission.status_code==201, submission.text
    assert client.get(f"/api/v1/submissions/{submission.json()['id']}",headers=user_b_headers).status_code==404
    assert client.get(f"/api/v1/contests/{contest_id}/submissions",headers=user_a_headers).json()["items"][0]["id"]==submission.json()["id"]

def test_leaderboard_ordering_penalty_infra_and_participant_ids(client):
    _,headers=new_user(client,"leaderboard-viewer")
    viewer_id=client.get("/api/v1/auth/me",headers=headers).json()["id"]
    with SessionLocal() as db:
        viewer=db.get(User,viewer_id)
        contest,pin,start=make_contest_graph(db,viewer,"leaderboard contest")
        people=[]
        for i in range(3):
            u=User(email=f"lb-{uuid4().hex}@example.test",name=f"LB {i}",password_hash="not-used"); db.add(u); db.flush()
            participant=ContestParticipant(contest_id=contest.id,user_id=u.id,status="registered"); db.add(participant); db.flush(); people.append(participant)
        def add_result(participant,minute,verdict):
            sub=Submission(contest_participant_id=participant.id,contest_id=contest.id,contest_problem_id=pin.id,problem_version_id=pin.problem_version_id,test_suite_id=pin.test_suite_id,source_code="x",language="python",runtime_config_snapshot={},submitted_at=start+timedelta(minutes=minute)); db.add(sub); db.flush()
            attempt=JudgeAttempt(submission_id=sub.id,attempt_number=1,reason="initial",status="completed"); db.add(attempt); db.flush()
            sub.authoritative_attempt_id=attempt.id; db.add(Verdict(judge_attempt_id=attempt.id,verdict=verdict,score=100 if verdict=="ACCEPTED" else 0)); db.flush()
        # A: 5 solve minutes plus a wrong answer penalty; infra must be ignored.
        add_result(people[0],2,"WRONG_ANSWER"); add_result(people[0],3,"JUDGE_INFRA_FAILURE"); add_result(people[0],5,"ACCEPTED")
        # B: 10 minutes, so B ranks before A on penalty despite solving later.
        add_result(people[1],10,"ACCEPTED")
        contest.status="published"; db.commit()
        contest_id=contest.id; expected_ids=[p.id for p in people]
    result=client.get(f"/api/v1/contests/{contest_id}/leaderboard?limit=2",headers=headers)
    assert result.status_code==200, result.text
    rows=result.json()["items"]
    assert [row["participant_id"] for row in rows]==[expected_ids[1],expected_ids[0]]
    assert [row["solved"] for row in rows]==[1,1]
    assert rows[0]["penalty"] < rows[1]["penalty"]
    cursor=result.json()["next_cursor"]
    assert cursor
    next_page=client.get(f"/api/v1/contests/{contest_id}/leaderboard?limit=2&cursor={cursor}",headers=headers)
    assert next_page.status_code==200, next_page.text
    assert [r["participant_id"] for r in next_page.json()["items"]]==[expected_ids[2]]
    assert next_page.json()["next_cursor"] is None
    with SessionLocal() as db:
        contest=db.get(Contest,contest_id)
        statement=leaderboard_statement(contest_id,contest).compile(dialect=db.get_bind().dialect,compile_kwargs={"literal_binds":True})
        plan=db.execute(text("EXPLAIN FORMAT=JSON "+str(statement))).scalar_one()
        if isinstance(plan,str): plan=json.loads(plan)
        assert "query_block" in plan
