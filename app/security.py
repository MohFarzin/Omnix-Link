from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer, URLSafeTimedSerializer
from passlib.context import CryptContext

from .config import get_settings

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return pwd.verify(password, password_hash)


def session_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="omnix-link-session")


def oauth_state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="omnix-link-oauth")


def dump_session(user_id: int) -> str:
    return session_serializer().dumps({"uid": user_id})


def load_session(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = session_serializer().loads(token)
        return int(data["uid"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None


def dump_oauth_state(payload: dict) -> str:
    return oauth_state_serializer().dumps(payload)


def load_oauth_state(token: str, max_age: int = 900) -> dict:
    return oauth_state_serializer().loads(token, max_age=max_age)
