from sqlalchemy.orm import Session
from modules.users.models import User

def get_user_by_id(db: Session, user_id: str):
    return db.query(User).filter(User.user_id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def create_user(db: Session, new_user: User):
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
