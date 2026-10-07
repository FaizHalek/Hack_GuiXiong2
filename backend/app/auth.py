"""Local accounts: scrypt password hashes and HS256 tokens signed with the app secret.

Two token kinds share the secret and are told apart by `typ`:
  access  the bearer token the browser sends with every API call
  file    a short-lived link to one PDF, so the viewer can load it without headers
"""

import hashlib
import hmac
import secrets
import time

import jwt

from app.config import get_settings
from app.db import app_secret

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
FILE_TOKEN_TTL_S = 3600


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def _encode(claims: dict, ttl_s: int) -> str:
    issued = int(time.time())
    return jwt.encode({**claims, "iat": issued, "exp": issued + ttl_s}, app_secret(), algorithm="HS256")


def _decode(token: str, typ: str) -> dict:
    claims = jwt.decode(token, app_secret(), algorithms=["HS256"])
    if claims.get("typ") != typ:
        raise jwt.InvalidTokenError(f"expected a {typ} token")
    return claims


def create_access_token(user_id: str) -> str:
    return _encode({"sub": user_id, "typ": "access"}, get_settings().token_ttl_hours * 3600)


def decode_access_token(token: str) -> dict:
    return _decode(token, "access")


def create_file_token(document_id: str) -> str:
    return _encode({"doc": document_id, "typ": "file"}, FILE_TOKEN_TTL_S)


def decode_file_token(token: str) -> dict:
    return _decode(token, "file")
