"""Autenticação por sessão (token aleatório em cookie HttpOnly, hash no banco)
e dependências de autorização por perfil."""
from datetime import datetime

from fastapi import Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import LoginRequired, PermissionDenied
from app.models import ROLE_DOCTOR, ROLE_PATIENT, LoginSession, User, utcnow
from app.security import DUMMY_HASH, hash_token, new_session_token, verify_password

SESSION_COOKIE = "telemed_sessao"


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not user.is_active:
        verify_password(password, DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def start_session(db: Session, user: User, response: Response) -> None:
    token = new_session_token()
    now = utcnow()
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
    db.add(LoginSession(token_hash=hash_token(token), user_id=user.id, expires_at=now + settings.session_duration))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.session_duration.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def end_session(db: Session, token: str | None, response: Response) -> None:
    if token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def user_from_token(db: Session, token: str | None, now: datetime | None = None) -> User | None:
    if not token or len(token) > 200:
        return None
    now = now or utcnow()
    session = db.scalar(
        select(LoginSession).where(LoginSession.token_hash == hash_token(token), LoginSession.expires_at > now)
    )
    if session is None or not session.user.is_active:
        return None
    return session.user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    return user_from_token(db, request.cookies.get(SESSION_COOKIE))


def require_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_patient(user: User = Depends(require_user)) -> User:
    if user.role != ROLE_PATIENT:
        raise PermissionDenied("Esta área é exclusiva para pacientes.")
    return user


def require_doctor(user: User = Depends(require_user)) -> User:
    if user.role != ROLE_DOCTOR:
        raise PermissionDenied("Esta área é exclusiva para médicos.")
    return user
