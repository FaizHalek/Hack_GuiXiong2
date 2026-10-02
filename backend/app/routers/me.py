from fastapi import APIRouter, Depends

from app.deps import CurrentUser, get_current_user

router = APIRouter(tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    labels = (
        user.db.table("labels").select("id,name,description,color").in_("id", user.label_ids).order("name").execute().data
        if user.label_ids
        else []
    )
    return {"id": user.id, "email": user.email, "role": user.role, "labels": labels}
