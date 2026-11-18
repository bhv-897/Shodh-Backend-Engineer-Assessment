import base64, json
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session
from app.models import OrganizationMembership

def get_role(db:Session,user_id:int,org_id:int):
    return db.scalar(select(OrganizationMembership.role).where(OrganizationMembership.user_id==user_id,OrganizationMembership.organization_id==org_id))
def require_org(db,user_id,org_id,roles=None):
    role=get_role(db,user_id,org_id)
    if role is None: raise HTTPException(404,"NOT_FOUND")
    if roles and role not in roles: raise HTTPException(403,"FORBIDDEN")
    return role
def page(db, query, sort_col, id_col, limit:int=20, cursor:str|None=None, descending:bool=False):
    if not 1 <= limit <= 100:
        raise HTTPException(422,"VALIDATION_ERROR")
    if cursor:
        try:
            raw=json.loads(base64.urlsafe_b64decode(cursor.encode()+b"="*((4-len(cursor)%4)%4)))
            value=raw["sort"]; last_id=int(raw["id"])
            if sort_col.type.python_type is datetime: value=datetime.fromisoformat(value)
            elif sort_col.type.python_type is int: value=int(value)
            op=sort_col.__lt__ if descending else sort_col.__gt__
            id_op=id_col.__lt__ if descending else id_col.__gt__
            query=query.where(or_(op(value),and_(sort_col==value,id_op(last_id))))
        except Exception:
            raise HTTPException(422,"VALIDATION_ERROR")
    direction=sort_col.desc() if descending else sort_col.asc()
    id_direction=id_col.desc() if descending else id_col.asc()
    rows=db.scalars(query.order_by(direction,id_direction).limit(limit+1)).all()
    more=len(rows)>limit; items=rows[:limit]; next_cursor=None
    if more and items:
        row=items[-1]; value=getattr(row,sort_col.key)
        encoded=value.isoformat() if isinstance(value,datetime) else value
        raw=json.dumps({"sort":encoded,"id":getattr(row,id_col.key)},separators=(",",":" )).encode()
        next_cursor=base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"items":items,"next_cursor":next_cursor}
