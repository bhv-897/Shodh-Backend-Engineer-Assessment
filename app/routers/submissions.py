from datetime import datetime, timezone
import hashlib, json
import logging
from fastapi import APIRouter, Depends, HTTPException, Response, Query, Header, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.config import settings
from app.models import User, Contest, ContestParticipant, ContestProblem, ProblemVersion, Submission, JudgeAttempt, Verdict, OutboxEvent, JudgeCaseResult, TestCase, IdempotencyRecord
from app.schemas import SubmissionCreate, RejudgeCreate, VerdictCreate
from app.permissions import get_role, page
from app.services.verdicts import record_verdict

router=APIRouter(tags=["submissions"])
logger=logging.getLogger("app.api.submissions")
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
def owned_or_organizer(db,u,s):
    p=db.get(ContestParticipant,s.contest_participant_id)
    if p and p.user_id==u.id: return
    c=db.get(Contest,s.contest_id)
    if c and get_role(db,u.id,c.organization_id) in {"owner","organizer"}: return
    raise HTTPException(404,"NOT_FOUND")
def _replay_idempotent_submission(db, user_id, contest_id, key, fingerprint, response):
    record=db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id==user_id,
        IdempotencyRecord.contest_id==contest_id,
        IdempotencyRecord.idempotency_key==key,
    ))
    if not record:
        return None
    if record.request_fingerprint != fingerprint:
        raise HTTPException(409,"IDEMPOTENCY_KEY_REUSED")
    submission=db.get(Submission,record.submission_id)
    if submission is None:
        return None
    response.status_code=200
    response.headers["Idempotent-Replayed"]="true"
    return submission

@router.post("/contests/{cid}/problems/{cpid}/submissions",status_code=201)
def submit(cid:int,cpid:int,request:Request,b:SubmissionCreate,response:Response,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key",max_length=128),u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one_or_none(); cp=db.scalar(select(ContestProblem).where(ContestProblem.id==cpid,ContestProblem.contest_id==cid))
    if not c or not cp: raise HTTPException(404,"NOT_FOUND")
    now=utcnow()
    if c.status!="published" or not(c.start_time<=now<=c.end_time): raise HTTPException(409,"CONTEST_NOT_OPEN")
    p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id).with_for_update())
    if not p or p.status!="registered": raise HTTPException(403,"NOT_REGISTERED")
    if b.language.lower()!="python": raise HTTPException(422,"VALIDATION_ERROR")
    if len(b.source_code.encode("utf-8"))>256*1024: raise HTTPException(413,"PAYLOAD_TOO_LARGE")
    canonical_request=json.dumps(
        {"contest_problem_id":cpid,"source_code":b.source_code,"language":b.language},
        sort_keys=True,separators=(",",":"),ensure_ascii=False,
    ) if idempotency_key is not None else None
    fingerprint=hashlib.sha256(canonical_request.encode("utf-8")).hexdigest() if canonical_request is not None else None
    if idempotency_key is not None:
        replay=_replay_idempotent_submission(db,u.id,cid,idempotency_key,fingerprint,response)
        if replay is not None:
            return replay
    # Serialize the submission/attempt write in a single transaction.
    version=db.get(ProblemVersion,cp.problem_version_id)
    s=Submission(contest_participant_id=p.id,contest_id=cid,contest_problem_id=cp.id,problem_version_id=cp.problem_version_id,test_suite_id=cp.test_suite_id,source_code=b.source_code,language="python",runtime_config_snapshot=version.runtime_configuration)
    db.add(s); db.flush(); a=JudgeAttempt(submission_id=s.id,attempt_number=1,reason="initial",requested_by_user_id=u.id,status="queued"); db.add(a); db.flush()
    db.add(OutboxEvent(judge_attempt_id=a.id,event_type="judge.requested",status="pending"))
    if idempotency_key is not None:
        db.add(IdempotencyRecord(user_id=u.id,contest_id=cid,idempotency_key=idempotency_key,
                                 request_fingerprint=fingerprint,submission_id=s.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key is not None:
            # Recheck registration after rollback before returning any prior submission.
            registered=db.scalar(select(ContestParticipant.id).where(
                ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id,
                ContestParticipant.status=="registered",
            ))
            if not registered:
                raise HTTPException(403,"NOT_REGISTERED")
            replay=_replay_idempotent_submission(db,u.id,cid,idempotency_key,fingerprint,response)
            if replay is not None:
                return replay
        raise
    db.refresh(s)
    logger.info("Submission queued",extra={
        "event":"submission.queued","request_id":request.state.request_id,
        "submission_id":s.id,"attempt_id":a.id,
    })
    return s

@router.post("/submissions/{sid}/rejudge",status_code=202)
def rejudge(sid:int,request:Request,b:RejudgeCreate|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.execute(select(Submission).where(Submission.id==sid).with_for_update()).scalar_one_or_none()
    if not s: raise HTTPException(404,"NOT_FOUND")
    contest=db.get(Contest,s.contest_id)
    role=get_role(db,u.id,contest.organization_id)
    if role is None: raise HTTPException(404,"NOT_FOUND")
    if role not in {"owner","organizer"}: raise HTTPException(403,"FORBIDDEN")
    if b:
        if b.problem_version_id is not None and b.problem_version_id!=s.problem_version_id: raise HTTPException(409,"PIN_MISMATCH")
        if b.test_suite_id is not None and b.test_suite_id!=s.test_suite_id: raise HTTPException(409,"PIN_MISMATCH")
    active=db.scalar(select(JudgeAttempt.id).where(
        JudgeAttempt.submission_id==sid,JudgeAttempt.status.in_(("queued","running"))
    ).with_for_update())
    if active is not None: raise HTTPException(409,"ATTEMPT_IN_PROGRESS")
    attempt_number=db.scalar(select(func.coalesce(func.max(JudgeAttempt.attempt_number),0)).where(JudgeAttempt.submission_id==sid))+1
    attempt=JudgeAttempt(
        submission_id=sid,attempt_number=attempt_number,reason="rejudge",
        requested_by_user_id=u.id,status="queued",
    )
    db.add(attempt)
    db.flush()
    db.add(OutboxEvent(judge_attempt_id=attempt.id,event_type="judge.requested",status="pending"))
    db.commit()
    db.refresh(attempt)
    logger.info("Rejudge queued",extra={
        "event":"submission.rejudge.queued","request_id":request.state.request_id,
        "submission_id":sid,"attempt_id":attempt.id,
    })
    return attempt

@router.get("/contests/{cid}/submissions")
def contest_submissions(cid:int,limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.get(Contest,cid)
    if not c: raise HTTPException(404,"NOT_FOUND")
    role=get_role(db,u.id,c.organization_id); q=select(Submission).where(Submission.contest_id==cid)
    if role not in {"owner","organizer"}:
        p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id))
        if not p: raise HTTPException(404,"NOT_FOUND")
        q=q.where(Submission.contest_participant_id==p.id)
    return page(db,q,Submission.submitted_at,Submission.id,limit,cursor,descending=True)
@router.get("/submissions/{sid}")
def submission(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); return s
@router.get("/submissions/{sid}/result")
def submission_result(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s)
    organizer=get_role(db,u.id,db.get(Contest,s.contest_id).organization_id) in {"owner","organizer"}
    attempt=db.get(JudgeAttempt,s.authoritative_attempt_id) if s.authoritative_attempt_id else db.scalar(
        select(JudgeAttempt).where(JudgeAttempt.submission_id==sid).order_by(JudgeAttempt.attempt_number.desc(),JudgeAttempt.id.desc()).limit(1)
    )
    if not attempt:
        return {"submission_id":s.id,"status":s.status,"attempt":None,"cases":[]}
    verdict=db.scalar(select(Verdict).where(Verdict.judge_attempt_id==attempt.id))
    result=None
    if verdict:
        result={"verdict":verdict.verdict,"public_message":verdict.public_message}
    case_rows=db.execute(
        select(JudgeCaseResult,TestCase.is_hidden)
        .join(TestCase,TestCase.id==JudgeCaseResult.test_case_id)
        .where(JudgeCaseResult.judge_attempt_id==attempt.id)
        .order_by(JudgeCaseResult.ordinal)
    ).all()
    cases=[]
    for case_result,is_hidden in case_rows:
        if organizer:
            cases.append({"case_number":case_result.ordinal if organizer else len(cases)+1,
                          "verdict":case_result.verdict,"execution_time_ms":case_result.execution_time_ms})
    return {"submission_id":s.id,"status":s.status,"attempt_number":attempt.attempt_number,
            "attempt_status":attempt.status,"result":result,"cases":cases}
@router.get("/submissions/{sid}/source")
def source(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); return {"source_code":s.source_code,"language":s.language}
@router.get("/submissions/{sid}/attempts")
def attempts(sid:int,limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); private=get_role(db,u.id,db.get(Contest,s.contest_id).organization_id) in {"owner","organizer"}
    result=page(db,select(JudgeAttempt).where(JudgeAttempt.submission_id==sid),JudgeAttempt.attempt_number,JudgeAttempt.id,limit,cursor); out=[]
    for a in result["items"]:
        v=db.scalar(select(Verdict).where(Verdict.judge_attempt_id==a.id)); row={"id":a.id,"attempt_number":a.attempt_number,"reason":a.reason,"status":a.status,"created_at":a.created_at,"completed_at":a.completed_at}
        if v: row["verdict"]={"verdict":v.verdict,"score":v.score,"execution_time_ms":v.execution_time_ms,"memory_used_kb":v.memory_used_kb,"public_message":v.public_message,**({"private_diagnostics":v.private_diagnostics} if private else {})}
        out.append(row)
    return {"items":out,"next_cursor":result["next_cursor"]}
@router.post("/dev/attempts/{attempt_id}/verdict",include_in_schema=False)
def dev_verdict(attempt_id:int,b:VerdictCreate,db:Session=Depends(get_db)):
    if not settings.enable_dev_endpoints: raise HTTPException(404,"NOT_FOUND")
    try: return record_verdict(db,attempt_id,**b.model_dump())
    except ValueError as e: raise HTTPException(409,str(e))
