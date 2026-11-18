from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, OrganizationMembership, Organization
from app.schemas import Register, Login
from app.auth import hash_password, verify_password, issue_token, get_current_user

router=APIRouter(prefix="/auth",tags=["auth"])
def user_out(u): return {"id":u.id,"email":u.email,"name":u.name,"created_at":u.created_at}
@router.post("/register",status_code=201)
def register(body:Register,db:Session=Depends(get_db)):
    email=body.email.strip().lower()
    if db.scalar(select(User.id).where(User.email==email)): raise HTTPException(409,"EMAIL_TAKEN")
    u=User(email=email,name=body.name,password_hash=hash_password(body.password)); db.add(u)
    try: db.commit(); db.refresh(u)
    except IntegrityError: db.rollback(); raise HTTPException(409,"EMAIL_TAKEN")
    return user_out(u)
@router.post("/login")
def login(body:Login,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==body.email.strip().lower()))
    if not u or not verify_password(body.password,u.password_hash): raise HTTPException(401,"INVALID_CREDENTIALS")
    return {"access_token":issue_token(u),"token_type":"bearer"}
@router.get("/me")
def me(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    memberships=db.execute(select(OrganizationMembership,Organization.name).join(Organization).where(OrganizationMembership.user_id==user.id).order_by(OrganizationMembership.organization_id)).all()
    return {**user_out(user),"memberships":[{"organization_id":m.organization_id,"name":name,"role":m.role} for m,name in memberships]}
