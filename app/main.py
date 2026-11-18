import uuid, logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.logging_config import configure_json_logging
configure_json_logging()

from app.db import get_db
from app.routers import auth, organizations, problems, contests, submissions

app=FastAPI(title="Easecoding Contest API",version="1.0.0")
api_logger=logging.getLogger("app.api")
def error_body(request,code,message,details=None):
    return {"error":{"code":code,"message":message,"details":details or [],"request_id":getattr(request.state,"request_id","")}}
@app.exception_handler(HTTPException)
async def http_error_handler(request:Request,exc:HTTPException):
    code=str(exc.detail or "REQUEST_ERROR")
    message={"INVALID_CREDENTIALS":"Invalid email or password","INVALID_TOKEN":"Authentication required","NOT_FOUND":"Resource not found","FORBIDDEN":"Insufficient permissions"}.get(code,code.replace("_"," ").capitalize())
    return JSONResponse(status_code=exc.status_code,content=error_body(request,code,message))
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request:Request,exc:RequestValidationError):
    details=[{"field":".".join(str(x) for x in e.get("loc",())[1:]),"message":e.get("msg","Invalid value")} for e in exc.errors()]
    return JSONResponse(status_code=422,content=error_body(request,"VALIDATION_ERROR","Request validation failed",details))
@app.middleware("http")
async def request_id_middleware(request:Request,call_next):
    rid=request.headers.get("X-Request-ID") or str(uuid.uuid4()); request.state.request_id=rid
    try: response=await call_next(request)
    except Exception:
        api_logger.exception("Unhandled request error",extra={"event":"http.request.failure","request_id":rid,"submission_id":None,"attempt_id":None})
        response=JSONResponse(status_code=500,content={"error":{"code":"INTERNAL_ERROR","message":"An internal error occurred","details":[],"request_id":rid}})
    response.headers["X-Request-ID"]=rid
    api_logger.info("HTTP request completed",extra={
        "event":"http.request.completed","request_id":rid,
        "submission_id":None,"attempt_id":None,"status_code":response.status_code,
    })
    return response
@app.exception_handler(IntegrityError)
@app.exception_handler(DBAPIError)
async def db_error_handler(request:Request,exc):
    raw=str(getattr(exc,"orig",exc)); code="CONFLICT"
    if "PUBLISHED_VERSION_IMMUTABLE" in raw: code="PUBLISHED_VERSION_IMMUTABLE"
    elif "ACTIVE_SUITE_IMMUTABLE" in raw: code="ACTIVE_SUITE_IMMUTABLE"
    elif "LAST_OWNER_REQUIRED" in raw: code="LAST_OWNER_REQUIRED"
    elif "MEMBER_IS_CONTEST_ORGANIZER" in raw: code="MEMBER_IS_CONTEST_ORGANIZER"
    elif "45000" in raw: code="DATABASE_RULE_VIOLATION"
    return JSONResponse(status_code=409,content=error_body(request,code,"The request conflicts with the current resource state"))
@app.exception_handler(Exception)
async def generic_error_handler(request:Request,exc):
    logging.exception("Unhandled request error")
    return JSONResponse(status_code=500,content={"error":{"code":"INTERNAL_ERROR","message":"An internal error occurred","details":[],"request_id":getattr(request.state,"request_id","")}})
@app.get("/health")
def health(): return {"status":"ok"}
app.include_router(auth.router,prefix="/api/v1")
app.include_router(organizations.router,prefix="/api/v1")
app.include_router(problems.router,prefix="/api/v1")
app.include_router(contests.router,prefix="/api/v1")
app.include_router(submissions.router,prefix="/api/v1")
