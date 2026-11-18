from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.models import User, Problem, ProblemVersion, TestSuite, TestCase
from app.permissions import require_org
from app.schemas import ProblemCreate, VersionCreate, CaseCreate

router=APIRouter(tags=["problems"])
def problem_or_404(db,pid):
    p=db.get(Problem,pid)
    if not p: raise HTTPException(404,"NOT_FOUND")
    return p
def version_or_404(db,vid):
    v=db.get(ProblemVersion,vid)
    if not v: raise HTTPException(404,"NOT_FOUND")
    return v
def suite_org(db,sid):
    s=db.get(TestSuite,sid)
    if not s: raise HTTPException(404,"NOT_FOUND")
    v=version_or_404(db,s.problem_version_id); p=problem_or_404(db,v.problem_id); return s,p
@router.post("/organizations/{oid}/problems",status_code=201)
def create_problem(oid:int,b:ProblemCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid,{"owner","organizer"}); p=Problem(organization_id=oid,title=b.title); db.add(p); db.commit(); db.refresh(p); return p
@router.get("/organizations/{oid}/problems")
def org_problems(oid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid); rows=db.scalars(select(Problem).where(Problem.organization_id==oid).order_by(Problem.id).limit(101)).all(); return {"items":rows,"next_cursor":None}
@router.get("/problems/{pid}")
def get_problem(pid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    p=problem_or_404(db,pid); require_org(db,u.id,p.organization_id); return p
@router.post("/problems/{pid}/versions",status_code=201)
def create_version(pid:int,b:VersionCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    p=problem_or_404(db,pid); require_org(db,u.id,p.organization_id,{"owner","organizer"}); db.execute(select(Problem).where(Problem.id==pid).with_for_update()).scalar_one(); n=(db.scalar(select(func.max(ProblemVersion.version_number)).where(ProblemVersion.problem_id==pid)) or 0)+1
    v=ProblemVersion(problem_id=pid,version_number=n,statement=b.statement,execution_limits=b.execution_limits,runtime_configuration=b.runtime_configuration); db.add(v); db.commit(); db.refresh(v); return v
@router.get("/problems/{pid}/versions")
def versions(pid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    p=problem_or_404(db,pid); role=require_org(db,u.id,p.organization_id); q=select(ProblemVersion).where(ProblemVersion.problem_id==pid)
    if role=="member": q=q.where(ProblemVersion.published_at.is_not(None))
    return {"items":db.scalars(q.order_by(ProblemVersion.version_number,ProblemVersion.id).limit(101)).all(),"next_cursor":None}
@router.post("/problem-versions/{vid}/publish")
def publish(vid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    v=version_or_404(db,vid); p=problem_or_404(db,v.problem_id); require_org(db,u.id,p.organization_id,{"owner","organizer"}); v=db.execute(select(ProblemVersion).where(ProblemVersion.id==vid).with_for_update()).scalar_one()
    if v.published_at: raise HTTPException(409,"ALREADY_PUBLISHED")
    from sqlalchemy import func as f
    v.published_at=db.scalar(select(f.utc_timestamp(6))); db.commit(); db.refresh(v); return v
@router.post("/problem-versions/{vid}/test-suites",status_code=201)
def create_suite(vid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    v=version_or_404(db,vid); p=problem_or_404(db,v.problem_id); require_org(db,u.id,p.organization_id,{"owner","organizer"}); db.execute(select(ProblemVersion).where(ProblemVersion.id==vid).with_for_update()).scalar_one(); n=(db.scalar(select(func.max(TestSuite.version_number)).where(TestSuite.problem_version_id==vid)) or 0)+1
    s=TestSuite(problem_version_id=vid,version_number=n,status="draft"); db.add(s); db.commit(); db.refresh(s); return s
@router.get("/problem-versions/{vid}/test-suites")
def suites(vid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    v=version_or_404(db,vid); p=problem_or_404(db,v.problem_id); role=require_org(db,u.id,p.organization_id); q=select(TestSuite).where(TestSuite.problem_version_id==vid)
    if role=="member": q=q.where(TestSuite.status.in_(["active","retired"]))
    return {"items":db.scalars(q.order_by(TestSuite.version_number,TestSuite.id).limit(101)).all(),"next_cursor":None}
@router.post("/test-suites/{sid}/test-cases",status_code=201)
def create_case(sid:int,b:CaseCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s,p=suite_org(db,sid); require_org(db,u.id,p.organization_id,{"owner","organizer"}); s=db.execute(select(TestSuite).where(TestSuite.id==sid).with_for_update()).scalar_one()
    if s.status!="draft": raise HTTPException(409,"SUITE_NOT_EDITABLE")
    c=TestCase(test_suite_id=sid,**b.model_dump()); db.add(c); db.commit(); db.refresh(c); return c
@router.get("/test-suites/{sid}/test-cases")
def cases(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s,p=suite_org(db,sid); require_org(db,u.id,p.organization_id,{"owner","organizer"}); rows=db.scalars(select(TestCase).where(TestCase.test_suite_id==sid).order_by(TestCase.id).limit(101)).all(); return {"items":rows,"next_cursor":None}
@router.post("/test-suites/{sid}/activate")
def activate(sid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    s,p=suite_org(db,sid); require_org(db,u.id,p.organization_id,{"owner","organizer"}); s=db.execute(select(TestSuite).where(TestSuite.id==sid).with_for_update()).scalar_one()
    if s.status!="draft": raise HTTPException(409,"SUITE_NOT_EDITABLE")
    if not db.scalar(select(TestCase.id).where(TestCase.test_suite_id==sid).limit(1)): raise HTTPException(400,"NO_TEST_CASES")
    db.execute(TestSuite.__table__.update().where(TestSuite.problem_version_id==s.problem_version_id,TestSuite.status=="active").values(status="retired")); s.status="active"; db.commit(); db.refresh(s); return s
