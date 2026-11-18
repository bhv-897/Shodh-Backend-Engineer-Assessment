from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import get_current_user
from app.models import User, Organization, OrganizationMembership, Contest
from app.permissions import require_org, get_role
from app.schemas import OrgCreate, MemberAdd, RoleUpdate

router=APIRouter(tags=["organizations"])
@router.post("/organizations",status_code=201)
def create_org(b:OrgCreate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    o=Organization(name=b.name); db.add(o); db.flush(); db.add(OrganizationMembership(organization_id=o.id,user_id=u.id,role="owner")); db.commit(); db.refresh(o); return o
@router.get("/organizations")
def list_orgs(u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return {"items":db.scalars(select(Organization).join(OrganizationMembership).where(OrganizationMembership.user_id==u.id).order_by(Organization.id).limit(101)).all(),"next_cursor":None}
@router.get("/organizations/{oid}")
def get_org(oid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid); o=db.get(Organization,oid)
    if not o: raise HTTPException(404,"NOT_FOUND")
    return o
@router.post("/organizations/{oid}/members",status_code=201)
def add_member(oid:int,b:MemberAdd,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid,{"owner"})
    if b.role not in {"organizer","member","owner"}: raise HTTPException(422,"VALIDATION_ERROR")
    target=db.scalar(select(User).where(User.email==b.email.strip().lower()))
    if not target: raise HTTPException(404,"USER_NOT_FOUND")
    if get_role(db,target.id,oid): raise HTTPException(409,"ALREADY_MEMBER")
    m=OrganizationMembership(organization_id=oid,user_id=target.id,role=b.role); db.add(m); db.commit(); db.refresh(m); return m
@router.get("/organizations/{oid}/members")
def members(oid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid); ms=db.scalars(select(OrganizationMembership).where(OrganizationMembership.organization_id==oid).order_by(OrganizationMembership.id).limit(101)).all()
    return {"items":ms,"next_cursor":None}
def protect_membership_change(db,oid,uid,new_role=None):
    old=get_role(db,uid,oid)
    if not old: raise HTTPException(404,"NOT_FOUND")
    if old=="owner" and new_role!="owner" and db.scalar(select(func.count()).select_from(OrganizationMembership).where(OrganizationMembership.organization_id==oid,OrganizationMembership.role=="owner"))<=1: raise HTTPException(409,"LAST_OWNER_REQUIRED")
    if old=="organizer" and new_role!="organizer":
        if db.scalar(select(Contest.id).where(Contest.organization_id==oid,Contest.organizer_id==uid,Contest.status!="archived").limit(1)): raise HTTPException(409,"MEMBER_IS_CONTEST_ORGANIZER")
@router.patch("/organizations/{oid}/members/{uid}")
def update_member(oid:int,uid:int,b:RoleUpdate,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid,{"owner"})
    if b.role not in {"owner","organizer","member"}: raise HTTPException(422,"VALIDATION_ERROR")
    protect_membership_change(db,oid,uid,b.role); m=db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==oid,OrganizationMembership.user_id==uid)); m.role=b.role; db.commit(); return m
@router.delete("/organizations/{oid}/members/{uid}",status_code=204)
def delete_member(oid:int,uid:int,u:User=Depends(get_current_user),db:Session=Depends(get_db)):
    require_org(db,u.id,oid,{"owner"}); protect_membership_change(db,oid,uid,None); m=db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==oid,OrganizationMembership.user_id==uid)); db.delete(m); db.commit(); return Response(status_code=204)
