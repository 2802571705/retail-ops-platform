import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User

SECRET = os.getenv("JWT_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("请在项目根目录 .env 中配置至少 32 字符的 JWT_SECRET")

hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def password_hash(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return hasher.verify(password, stored_hash)


def create_token(user_id: int) -> str:
    claims = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(401, "请先登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(401, "登录已失效，请重新登录") from None
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(401, "账号不存在或已停用")
    return user
