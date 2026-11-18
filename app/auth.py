from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import User

hasher=PasswordHasher()
def hash_password(password:str)->str: return hasher.hash(password)
def verify_password(password:str, hashed:str)->bool:
    try: return hasher.verify(hashed,password)
    except (VerifyMismatchError,InvalidHash): return False
def issue_token(user:User)->str:
    now=datetime.now(timezone.utc)
    return jwt.encode({"sub":str(user.id),"iat":now,"exp":now+timedelta(minutes=settings.jwt_expiry_minutes)},settings.jwt_secret,algorithm="HS256")
def get_current_user(authorization:str|None=Header(default=None),db:Session=Depends(get_db))->User:
    if not authorization or not authorization.lower().startswith("bearer "): raise HTTPException(401,"INVALID_TOKEN")
    try:
        data=jwt.decode(authorization[7:].strip(),settings.jwt_secret,algorithms=["HS256"])
        user=db.get(User,int(data["sub"]))
    except Exception: user=None
    if not user: raise HTTPException(401,"INVALID_TOKEN")
    return user
