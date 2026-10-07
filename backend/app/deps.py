from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import decode_access_token
from app.db import connect, fetch_all, fetch_one

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    token: str = ""
    label_ids: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e

    with connect() as conn:
        user = fetch_one(conn, "select id, email, role from users where id = ?", (claims["sub"],))
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account no longer exists")
        if user["role"] == "admin":
            label_ids = [r["id"] for r in fetch_all(conn, "select id from labels")]
        else:
            rows = fetch_all(conn, "select label_id from user_label_grants where user_id = ?", (user["id"],))
            label_ids = [r["label_id"] for r in rows]

    return CurrentUser(id=user["id"], email=user["email"], role=user["role"], token=creds.credentials, label_ids=label_ids)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def authorised_labels(requested: list[str] | None, user: CurrentUser) -> list[str]:
    """Intersect the labels a request asks for with the labels the user holds.

    An empty/None request means "all of my collections".
    """
    granted = set(user.label_ids)
    if not requested:
        return sorted(granted)
    return sorted(granted.intersection(requested))
