from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.config import get_settings
from app.db import user_client

bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    token: str
    label_ids: list[str] = field(default_factory=list)
    db: Client | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    url = f"{get_settings().supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True)


def verify_token(token: str) -> dict:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if not s.supabase_jwt_secret:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "HS256 token but no JWT secret configured")
            return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        key = _jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["RS256", "ES256"], audience="authenticated")
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    claims = verify_token(creds.credentials)
    db = user_client(creds.credentials)

    profile = db.table("profiles").select("id,email,role").eq("id", claims["sub"]).maybe_single().execute()
    if profile is None or not profile.data:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No profile for this user")

    if profile.data["role"] == "admin":
        labels = db.table("labels").select("id").execute().data
        label_ids = [row["id"] for row in labels]
    else:
        grants = db.table("user_label_grants").select("label_id").eq("user_id", claims["sub"]).execute().data
        label_ids = [row["label_id"] for row in grants]

    return CurrentUser(
        id=claims["sub"],
        email=profile.data["email"],
        role=profile.data["role"],
        token=creds.credentials,
        label_ids=label_ids,
        db=db,
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def authorised_labels(requested: list[str] | None, user: CurrentUser) -> list[str]:
    """Intersect the labels a request asks for with the labels the user holds.

    An empty/None request means "all of my libraries".
    """
    granted = set(user.label_ids)
    if not requested:
        return sorted(granted)
    return sorted(granted.intersection(requested))
