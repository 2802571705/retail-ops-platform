from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_token, current_user, password_hash, verify_password
from app.models import MemberAccount, User

router = APIRouter(prefix="/auth", tags=["身份认证"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


def user_data(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, db: Session = Depends(get_db)):
    email = str(body.email).lower()
    user = User(email=email, password_hash=password_hash(body.password),
                display_name=body.display_name.strip(), role="CONSUMER", status="ACTIVE")
    db.add(user)
    try:
        db.flush()
        db.add(MemberAccount(user_id=user.id, points_balance=0))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该邮箱已注册") from None
    return {"data": user_data(user), "error": None, "request_id": request.state.request_id}


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if user is None or user.status != "ACTIVE" or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    return {"data": {"access_token": create_token(user.id), "token_type": "bearer", "user": user_data(user)},
            "error": None, "request_id": request.state.request_id}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"data": user_data(user), "error": None, "request_id": request.state.request_id}
