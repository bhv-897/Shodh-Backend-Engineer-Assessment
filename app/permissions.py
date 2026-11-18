from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import OrganizationMembership

def get_role(db:Session,user_id:int,org_id:int):
    return db.scalar(select(OrganizationMembership.role).where(OrganizationMembership.user_id==user_id,OrganizationMembership.organization_id==org_id))
def require_org(db,user_id,org_id,roles=None):
    role=get_role(db,user_id,org_id)
    if role is None: raise HTTPException(404,"NOT_FOUND")
    if roles and role not in roles: raise HTTPException(403,"FORBIDDEN")
    return role
def page(query,limit:int,offset:int=0):
    rows=query.limit(limit+1).offset(offset).all(); more=len(rows)>limit
    return {"items":rows[:limit],"next_cursor":None if not more else str(offset+limit)}
