import base64, json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy import select, func, and_, or_, case, literal_column, cast, Integer
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.models import User, Contest, Organization, OrganizationMembership, ContestProblem, Problem, ProblemVersion, TestSuite, ContestParticipant, Submission, JudgeAttempt, Verdict
from app.permissions import require_org, page
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
def org_contests(oid:int,limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid); return page(db,select(Contest).where(Contest.organization_id==oid),Contest.id,Contest.id,limit,cursor)
@router.get("/contests")
def all_contests(limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    # Hidden drafts are excluded unless caller belongs to their organization.
    member_orgs=select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id==u.id)
    q=select(Contest).where(Contest.status.in_(["published","archived"]) | Contest.organization_id.in_(member_orgs))
    return page(db,q,Contest.id,Contest.id,limit,cursor)
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
def contest_problems(cid:int,limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); role=None
    from app.permissions import get_role
    role=get_role(db,u.id,c.organization_id)
    if c.status=="draft" and role is None: raise HTTPException(404,"NOT_FOUND")
    result=page(db,select(ContestProblem).where(ContestProblem.contest_id==cid),ContestProblem.display_order,ContestProblem.id,limit,cursor)
    if not role: result["items"]=[{"id":r.id,"contest_id":r.contest_id,"problem_id":r.problem_id,"display_order":r.display_order,"points":r.points} for r in result["items"]]
    return result
@router.get("/contests/{cid}/problems/{cpid}")
def contest_problem(cid:int,cpid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid)
    from app.permissions import get_role
    role=get_role(db,u.id,c.organization_id)
    if c.status=="draft" and role is None: raise HTTPException(404,"NOT_FOUND")
    r=db.scalar(select(ContestProblem).where(ContestProblem.id==cpid,ContestProblem.contest_id==cid))
    if not r: raise HTTPException(404,"NOT_FOUND")
    if role is None: return {"id":r.id,"contest_id":r.contest_id,"problem_id":r.problem_id,"display_order":r.display_order,"points":r.points}
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
def participants(cid:int,limit:int=Query(20,ge=1,le=100),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid); organizer(db,u,c); return page(db,select(ContestParticipant).where(ContestParticipant.contest_id==cid),ContestParticipant.registered_at,ContestParticipant.id,limit,cursor)
def leaderboard_statement(cid:int,c:Contest):
    # One aggregate SQL statement over authoritative verdicts, ranked first solve per pin.
    accepted_rank=func.row_number().over(partition_by=(ContestParticipant.user_id,Submission.contest_problem_id),order_by=(Submission.submitted_at,Submission.id)).label("rn")
    accepted=select(ContestParticipant.user_id.label("uid"),Submission.contest_problem_id.label("pid"),Submission.id.label("sid"),Submission.submitted_at.label("sat"),accepted_rank).join(Submission,Submission.contest_participant_id==ContestParticipant.id).join(JudgeAttempt,JudgeAttempt.id==Submission.authoritative_attempt_id).join(Verdict,Verdict.judge_attempt_id==JudgeAttempt.id).where(ContestParticipant.contest_id==cid,ContestParticipant.status=="registered",Verdict.verdict=="ACCEPTED").subquery()
    solves=select(accepted.c.uid,accepted.c.pid,accepted.c.sid,accepted.c.sat).where(accepted.c.rn==1).subquery()
    wrong_count=select(func.count(Submission.id)).join(JudgeAttempt,JudgeAttempt.id==Submission.authoritative_attempt_id).join(Verdict,Verdict.judge_attempt_id==JudgeAttempt.id).where(Submission.contest_participant_id==ContestParticipant.id,Submission.contest_problem_id==solves.c.pid,Verdict.verdict!="ACCEPTED",Verdict.verdict!="JUDGE_INFRA_FAILURE",and_((Submission.submitted_at<solves.c.sat)|((Submission.submitted_at==solves.c.sat)&(Submission.id<solves.c.sid)))).correlate(ContestParticipant,solves).scalar_subquery()
    penalty=cast(func.coalesce(func.sum(func.timestampdiff(literal_column("MINUTE"),c.start_time,solves.c.sat)+func.coalesce(wrong_count,0)*c.penalty_minutes_per_wrong),0),Integer).label("penalty")
    solved=func.count(solves.c.sid).label("solved")
    return select(ContestParticipant.id.label("participant_id"),ContestParticipant.user_id.label("user_id"),solved,penalty,func.max(solves.c.sat).label("last_solved_at"),case((func.max(solves.c.sat).is_(None),1),else_=0).label("last_null")).select_from(ContestParticipant).outerjoin(solves,solves.c.uid==ContestParticipant.user_id).where(ContestParticipant.contest_id==cid,ContestParticipant.status=="registered").group_by(ContestParticipant.id,ContestParticipant.user_id)

def encode_leaderboard_cursor(row):
    value={"solved":int(row["solved"]),"penalty":int(row["penalty"]),"last_null":int(row["last_null"]),"last_solved_at":row["last_solved_at"].isoformat() if row["last_solved_at"] else None,"participant_id":int(row["participant_id"])}
    return base64.urlsafe_b64encode(json.dumps(value,separators=(",",":")).encode()).decode().rstrip("=")

@router.get("/contests/{cid}/leaderboard")
def leaderboard(cid:int,limit:int=Query(50,ge=1,le=200),offset:int|None=Query(default=None,ge=0),cursor:str|None=None,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    c=contest(db,cid)
    if c.status not in {"published","archived"}: raise HTTPException(404,"NOT_FOUND")
    if cursor and offset is not None: raise HTTPException(422,"VALIDATION_ERROR")
    q=leaderboard_statement(cid,c).subquery("leaderboard")
    if cursor:
        try:
            raw=json.loads(base64.urlsafe_b64decode(cursor.encode()+b"="*((4-len(cursor)%4)%4)))
            solved=int(raw["solved"]); penalty=int(raw["penalty"]); null_rank=int(raw["last_null"]); participant_id=int(raw["participant_id"])
            last_at=datetime.fromisoformat(raw["last_solved_at"]) if raw.get("last_solved_at") else None
            if null_rank not in (0,1) or (null_rank==0 and last_at is None): raise ValueError("invalid cursor")
        except Exception: raise HTTPException(422,"VALIDATION_ERROR")
        after_rank=or_(q.c.solved<solved,and_(q.c.solved==solved,q.c.penalty>penalty),and_(q.c.solved==solved,q.c.penalty==penalty,q.c.last_null>null_rank))
        same_rank=and_(q.c.solved==solved,q.c.penalty==penalty,q.c.last_null==null_rank)
        if null_rank==0:
            after_rank=or_(after_rank,and_(same_rank,q.c.last_solved_at>last_at),and_(same_rank,q.c.last_solved_at==last_at,q.c.participant_id>participant_id))
        else:
            after_rank=or_(after_rank,and_(same_rank,q.c.participant_id>participant_id))
        query=select(q).where(after_rank)
    else:
        query=select(q)
        if offset is not None: query=query.offset(offset)
    query=query.order_by(q.c.solved.desc(),q.c.penalty.asc(),q.c.last_null.asc(),q.c.last_solved_at.asc(),q.c.participant_id.asc()).limit(limit+1)
    rows=db.execute(query).mappings().all(); more=len(rows)>limit; items=[dict(r) for r in rows[:limit]]
    for row in items: row.pop("last_null",None)
    next_cursor=encode_leaderboard_cursor(rows[limit-1]) if more and items else None
    return {"items":items,"next_cursor":next_cursor}
