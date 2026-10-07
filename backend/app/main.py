import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import admin, chat, documents, me

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Government Knowledge Assistant", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().frontend_origin.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(me.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(admin.router)
