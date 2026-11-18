"""Create Swagger demo users. Run with: python -m scripts.seed_dev"""
from app.db import SessionLocal
from app.auth import hash_password
from app.models import User, Organization, OrganizationMembership

DEMOS=[("owner@example.test","Demo Owner","owner"),("organizer@example.test","Demo Organizer","organizer"),("member@example.test","Demo Member","member"),("participant@example.test","Demo Participant",None)]
def main():
    db=SessionLocal()
    try:
        org=db.query(Organization).filter_by(name="Easecoding Demo Organization").first()
        if not org: org=Organization(name="Easecoding Demo Organization"); db.add(org); db.flush()
        for email,name,role in DEMOS:
            user=db.query(User).filter_by(email=email).first()
            if not user: user=User(email=email,name=name,password_hash=hash_password("EasecodingDemo!2026")); db.add(user); db.flush()
            if role and not db.query(OrganizationMembership).filter_by(organization_id=org.id,user_id=user.id).first(): db.add(OrganizationMembership(organization_id=org.id,user_id=user.id,role=role))
        db.commit()
        print("Demo credentials: owner@example.test, organizer@example.test, member@example.test, participant@example.test; password EasecodingDemo!2026")
    finally: db.close()
if __name__=="__main__": main()
