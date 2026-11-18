from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.config import settings
from app.models import User, Contest, ContestParticipant, ContestProblem, ProblemVersion, Submission, JudgeAttempt, Verdict
from app.schemas import SubmissionCreate, VerdictCreate
from app.permissions import get_role
from app.services.verdicts import record_verdict

router=APIRouter(tags=["submissions"])
def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
def owned_or_organizer(db,u,s):
    p=db.get(ContestParticipant,s.contest_participant_id)
    if p and p.user_id==u.id: return
    c=db.get(Contest,s.contest_id)
    if c and get_role(db,u.id,c.organization_id) in {"owner","organizer"}: return
    raise HTTPException(404,"NOT_FOUND")
@router.post("/contests/{cid}/problems/{cpid}/submissions",status_code=201)
def submit(cid:int,cpid:int,b:SubmissionCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one_or_none(); cp=db.scalar(select(ContestProblem).where(ContestProblem.id==cpid,ContestProblem.contest_id==cid))
    if not c or not cp: raise HTTPException(404,"NOT_FOUND")
    now=utcnow()
    if c.status!="published" or not(c.start_time<=now<=c.end_time): raise HTTPException(409,"CONTEST_NOT_OPEN")
    p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id))
    if not p or p.status!="registered": raise HTTPException(403,"NOT_REGISTERED")
    if b.language.lower()!="python": raise HTTPException(422,"VALIDATION_ERROR")
    if len(b.source_code.encode("utf-8"))>256*1024: raise HTTPException(413,"PAYLOAD_TOO_LARGE")
    # Serialize the submission/attempt write in a single transaction.
    version=db.get(ProblemVersion,cp.problem_version_id)
    s=Submission(contest_participant_id=p.id,contest_id=cid,contest_problem_id=cp.id,problem_version_id=cp.problem_version_id,test_suite_id=cp.test_suite_id,source_code=b.source_code,language="python",runtime_config_snapshot=version.runtime_configuration)
    db.add(s); db.flush(); a=JudgeAttempt(submission_id=s.id,attempt_number=1,reason="initial",requested_by_user_id=u.id,status="queued"); db.add(a); db.commit(); db.refresh(s); return s
@router.get("/contests/{cid}/submissions")
def contest_submissions(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.get(Contest,cid)
    if not c: raise HTTPException(404,"NOT_FOUND")
    role=get_role(db,u.id,c.organization_id); q=select(Submission).where(Submission.contest_id==cid)
    if role not in {"owner","organizer"}:
        p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id))
        if not p: raise HTTPException(404,"NOT_FOUND")
        q=q.where(Submission.contest_participant_id==p.id)
    rows=db.scalars(q.order_by(Submission.submitted_at.desc(),Submission.id.desc()).limit(101)).all(); return {"items":rows,"next_cursor":None}
@router.get("/submissions/{sid}")
def submission(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); return s
@router.get("/submissions/{sid}/source")
def source(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); return {"source_code":s.source_code,"language":s.language}
@router.get("/submissions/{sid}/attempts")
def attempts(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s=db.get(Submission,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    owned_or_organizer(db,u,s); private=get_role(db,u.id,db.get(Contest,s.contest_id).organization_id) in {"owner","organizer"}
    rows=db.scalars(select(JudgeAttempt).where(JudgeAttempt.submission_id==sid).order_by(JudgeAttempt.attempt_number,JudgeAttempt.id)).all(); out=[]
    for a in rows:
        v=db.scalar(select(Verdict).where(Verdict.judge_attempt_id==a.id)); row={"id":a.id,"attempt_number":a.attempt_number,"reason":a.reason,"status":a.status,"created_at":a.created_at,"completed_at":a.completed_at}
        if v: row["verdict"]={"verdict":v.verdict,"score":v.score,"execution_time_ms":v.execution_time_ms,"memory_used_kb":v.memory_used_kb,"public_message":v.public_message,**({"private_diagnostics":v.private_diagnostics} if private else {})}
        out.append(row)
    return {"items":out,"next_cursor":None}
@router.post("/dev/attempts/{attempt_id}/verdict",include_in_schema=False)
def dev_verdict(attempt_id:int,b:VerdictCreate,db:Session=Depends(get_db)):
    if not settings.enable_dev_endpoints: raise HTTPException(404,"NOT_FOUND")
    try: return record_verdict(db,attempt_id,**b.model_dump())
    except ValueError as e: raise HTTPException(409,str(e))
