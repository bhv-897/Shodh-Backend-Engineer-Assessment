from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, func, and_, case
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.models import User, Contest, Organization, OrganizationMembership, ContestProblem, Problem, ProblemVersion, TestSuite, ContestParticipant, Submission, JudgeAttempt, Verdict
from app.permissions import require_org
from app.schemas import ContestCreate, ContestUpdate, ContestProblemCreate

router=APIRouter(tags=["contests"])
def now_utc(): return datetime.now(timezone.utc).replace(tzinfo=None)
def contest(db,cid):
    c=db.get(Contest,cid)
    if not c: raise HTTPException(404,"NOT_FOUND")
    return c
def organizer(db,u,c): return require_org(db,u.id,c.organization_id,{"owner","organizer"})
@router.post("/organizations/{oid}/contests",status_code=201)
def create_contest(oid:int,b:ContestCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid,{"owner","organizer"})
    start=b.start_time.astimezone(timezone.utc).replace(tzinfo=None) if b.start_time.tzinfo else b.start_time; end=b.end_time.astimezone(timezone.utc).replace(tzinfo=None) if b.end_time.tzinfo else b.end_time
    if end<=start: raise HTTPException(422,"VALIDATION_ERROR")
    c=Contest(organization_id=oid,organizer_id=u.id,title=b.title,start_time=start,end_time=end,scoring_mode=b.scoring_mode,penalty_minutes_per_wrong=b.penalty_minutes_per_wrong); db.add(c); db.commit(); db.refresh(c); return c
@router.get("/organizations/{oid}/contests")
def org_contests(oid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid); rows=db.scalars(select(Contest).where(Contest.organization_id==oid).order_by(Contest.id).limit(101)).all(); return {"items":rows,"next_cursor":None}
@router.get("/contests")
def all_contests(u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    # Hidden drafts are excluded unless caller belongs to their organization.
    member_orgs=select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id==u.id)
    q=select(Contest).where(Contest.status.in_(["published","archived"]) | Contest.organization_id.in_(member_orgs)).order_by(Contest.id).limit(101)
    rows=db.scalars(q).all(); return {"items":rows,"next_cursor":None}
@router.get("/contests/{cid}")
def get_contest(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid)
    if c.status=="draft": require_org(db,u.id,c.organization_id)
    return c
@router.patch("/contests/{cid}")
def patch_contest(cid:int,b:ContestUpdate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c); c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one()
    if c.status!="draft": raise HTTPException(409,"CONTEST_NOT_EDITABLE")
    for k,v in b.model_dump(exclude_unset=True).items(): setattr(c,k,v)
    if c.end_time<=c.start_time: raise HTTPException(422,"VALIDATION_ERROR")
    db.commit(); db.refresh(c); return c
@router.post("/contests/{cid}/publish")
def publish_contest(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c); c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one()
    if c.status!="draft": raise HTTPException(409,"CONTEST_NOT_EDITABLE")
    if not db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id==cid).limit(1)): raise HTTPException(400,"NO_CONTEST_PROBLEMS")
    c.status="published"; db.commit(); return c
@router.post("/contests/{cid}/archive")
def archive(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c)
    if c.end_time>now_utc(): raise HTTPException(409,"CONTEST_NOT_ENDED")
    c.status="archived"; db.commit(); return c
@router.post("/contests/{cid}/problems",status_code=201)
def add_problem(cid:int,b:ContestProblemCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c)
    p=db.get(Problem,b.problem_id)
    if not p or p.organization_id!=c.organization_id: raise HTTPException(404,"PROBLEM_NOT_FOUND")
    v=db.get(ProblemVersion,b.problem_version_id)
    if not v or v.problem_id!=p.id: raise HTTPException(400,"VERSION_MISMATCH")
    if v.published_at is None: raise HTTPException(400,"VERSION_NOT_PUBLISHED")
    s=db.get(TestSuite,b.test_suite_id)
    if not s or s.problem_version_id!=v.id: raise HTTPException(400,"SUITE_MISMATCH")
    if s.status!="active": raise HTTPException(400,"SUITE_NOT_ACTIVE")
    if db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id==cid,ContestProblem.problem_id==p.id)): raise HTTPException(409,"DUPLICATE_CONTEST_PROBLEM")
    if db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id==cid,ContestProblem.display_order==b.display_order)): raise HTTPException(409,"DISPLAY_ORDER_TAKEN")
    c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one()
    if c.status!="draft" and not(c.status=="published" and c.end_time>=now_utc()): raise HTTPException(409,"CONTEST_NOT_EDITABLE")
    cp=ContestProblem(contest_id=cid,organization_id=c.organization_id,**b.model_dump()); db.add(cp); db.commit(); db.refresh(cp); return cp
@router.get("/contests/{cid}/problems")
def contest_problems(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); role=None
    from app.permissions import get_role
    role=get_role(db,u.id,c.organization_id)
    rows=db.scalars(select(ContestProblem).where(ContestProblem.contest_id==cid).order_by(ContestProblem.display_order,ContestProblem.id).limit(101)).all()
    if not role: return {"items":[{"id":r.id,"contest_id":r.contest_id,"problem_id":r.problem_id,"display_order":r.display_order,"points":r.points} for r in rows],"next_cursor":None}
    return {"items":rows,"next_cursor":None}
@router.get("/contests/{cid}/problems/{cpid}")
def contest_problem(cid:int,cpid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    r=db.scalar(select(ContestProblem).where(ContestProblem.id==cpid,ContestProblem.contest_id==cid))
    if not r: raise HTTPException(404,"NOT_FOUND")
    from app.permissions import get_role
    if not get_role(db,u.id,contest(db,cid).organization_id): return {"id":r.id,"contest_id":r.contest_id,"problem_id":r.problem_id,"display_order":r.display_order,"points":r.points}
    return r
@router.delete("/contests/{cid}/problems/{cpid}",status_code=204)
def remove_problem(cid:int,cpid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c)
    if c.status!="draft": raise HTTPException(409,"CONTEST_NOT_EDITABLE")
    r=db.scalar(select(ContestProblem).where(ContestProblem.id==cpid,ContestProblem.contest_id==cid))
    if not r: raise HTTPException(404,"NOT_FOUND")
    if db.scalar(select(Submission.id).where(Submission.contest_problem_id==cpid).limit(1)): raise HTTPException(409,"PIN_IN_USE")
    db.delete(r); db.commit(); return Response(status_code=204)
@router.post("/contests/{cid}/register",status_code=201)
def register(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.execute(select(Contest).where(Contest.id==cid).with_for_update()).scalar_one_or_none()
    if not c: raise HTTPException(404,"NOT_FOUND")
    if c.status!="published" or c.end_time<now_utc(): raise HTTPException(409,"CONTEST_NOT_OPEN")
    p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id))
    if p and p.status=="disqualified": raise HTTPException(409,"PARTICIPANT_DISQUALIFIED")
    if p and p.status=="registered": raise HTTPException(409,"ALREADY_REGISTERED")
    if p: p.status="registered"
    else: p=ContestParticipant(contest_id=cid,user_id=u.id,status="registered"); db.add(p)
    db.commit(); db.refresh(p); return p
@router.delete("/contests/{cid}/register",status_code=204)
def unregister(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid)
    if c.end_time<=now_utc(): raise HTTPException(409,"CONTEST_ENDED")
    p=db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id==cid,ContestParticipant.user_id==u.id))
    if not p or p.status!="registered": raise HTTPException(404,"NOT_FOUND")
    p.status="withdrawn"; db.commit(); return Response(status_code=204)
@router.get("/contests/{cid}/participants")
def participants(cid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c); rows=db.scalars(select(ContestParticipant).where(ContestParticipant.contest_id==cid).order_by(ContestParticipant.registered_at,ContestParticipant.id).limit(101)).all(); return {"items":rows,"next_cursor":None}
@router.get("/contests/{cid}/leaderboard")
def leaderboard(cid:int,limit:int=50,offset:int=0,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid)
    if c.status not in {"published","archived"}: raise HTTPException(404,"NOT_FOUND")
    if not 1<=limit<=200 or offset<0: raise HTTPException(422,"VALIDATION_ERROR")
    # Single aggregate SQL statement over authoritative verdicts, ranked first solve per pin.
    from sqlalchemy import literal
    # Rank ACCEPTED authoritative verdicts per participant/pin; the first one is the solve.
    accepted_rank=func.row_number().over(partition_by=(ContestParticipant.user_id,Submission.contest_problem_id),order_by=(Submission.submitted_at,Submission.id)).label("rn")
    accepted=select(ContestParticipant.user_id.label("uid"),Submission.contest_problem_id.label("pid"),Submission.id.label("sid"),Submission.submitted_at.label("sat"),accepted_rank).join(Submission,Submission.contest_participant_id==ContestParticipant.id).join(JudgeAttempt,JudgeAttempt.id==Submission.authoritative_attempt_id).join(Verdict,Verdict.judge_attempt_id==JudgeAttempt.id).where(ContestParticipant.contest_id==cid,ContestParticipant.status=="registered",Verdict.verdict=="ACCEPTED").subquery()
    solves=select(accepted.c.uid,accepted.c.pid,accepted.c.sid,accepted.c.sat).where(accepted.c.rn==1).subquery()
    wrong_count=select(func.count(Submission.id)).join(JudgeAttempt,JudgeAttempt.id==Submission.authoritative_attempt_id).join(Verdict,Verdict.judge_attempt_id==JudgeAttempt.id).where(Submission.contest_participant_id==ContestParticipant.id,Submission.contest_problem_id==solves.c.pid,Verdict.verdict!="ACCEPTED",Verdict.verdict!="JUDGE_INFRA_FAILURE",and_((Submission.submitted_at<solves.c.sat)|((Submission.submitted_at==solves.c.sat)&(Submission.id<solves.c.sid)))).correlate(ContestParticipant,solves).scalar_subquery()
    q=select(ContestParticipant.user_id.label("participant_id"),func.count(solves.c.sid).label("solved"),func.coalesce(func.sum(func.timestampdiff(literal("MINUTE"),c.start_time,solves.c.sat)+func.coalesce(wrong_count,0)*c.penalty_minutes_per_wrong),0).label("penalty"),func.max(solves.c.sat).label("last_solved_at")).select_from(ContestParticipant).outerjoin(solves,solves.c.uid==ContestParticipant.user_id).where(ContestParticipant.contest_id==cid,ContestParticipant.status=="registered").group_by(ContestParticipant.user_id).order_by(func.count(solves.c.sid).desc(),"penalty",case((func.max(solves.c.sat).is_(None),1),else_=0),func.max(solves.c.sat),ContestParticipant.user_id).limit(limit).offset(offset)
    rows=db.execute(q).mappings().all(); return {"items":[dict(r) for r in rows],"next_cursor":None}
