from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import create_access_token, verify_password
from app.db import connect, fetch_all, fetch_one, placeholders
from app.deps import CurrentUser, get_current_user

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/login")
def login(body: LoginIn):
    with connect() as conn:
        user = fetch_one(conn, "select id, email, role, password_hash from users where email = ?", (body.email.strip(),))
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer"}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        labels = fetch_all(
            conn,
            f"select id, name, description, color from labels where id in ({placeholders(user.label_ids)}) order by name",
            user.label_ids,
        )
    return {"id": user.id, "email": user.email, "role": user.role, "labels": labels}
