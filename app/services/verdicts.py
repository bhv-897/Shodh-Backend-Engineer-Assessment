from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.models import JudgeAttempt, Submission, Verdict

def record_verdict(db:Session,attempt_id:int,verdict:str,score:int=0,execution_time_ms=None,memory_used_kb=None,public_message=None,private_diagnostics=None):
    with db.begin():
        a=db.execute(select(JudgeAttempt).where(JudgeAttempt.id==attempt_id).with_for_update()).scalar_one()
        if a.status not in {"queued","running"}: raise ValueError("ATTEMPT_NOT_ACTIVE")
        v=Verdict(judge_attempt_id=a.id,verdict=verdict,score=score,execution_time_ms=execution_time_ms,memory_used_kb=memory_used_kb,public_message=public_message,private_diagnostics=private_diagnostics); db.add(v)
        a.status="completed"; a.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
        s=db.execute(select(Submission).where(Submission.id==a.submission_id).with_for_update()).scalar_one()
        current=db.get(JudgeAttempt,s.authoritative_attempt_id) if s.authoritative_attempt_id else None
        if current is None or a.attempt_number>current.attempt_number:
            db.execute(update(Submission).where(Submission.id==s.id).values(authoritative_attempt_id=a.id,status="completed" if verdict!="JUDGE_INFRA_FAILURE" else ("failed" if current is None else "completed")))
    return v
