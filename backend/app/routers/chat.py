import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app.agents import pipeline
from app.deps import CurrentUser, authorised_labels, get_current_user
from app.llm.deepseek import LLMOutputError, RefusalError

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    label_ids: list[str] = []


class Feedback(BaseModel):
    value: Literal[1, -1]
    note: str | None = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    labels = authorised_labels(req.label_ids, user)
    if not labels:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to any of the selected libraries")

    db = user.db
    if req.conversation_id:
        convo = db.table("conversations").select("id").eq("id", req.conversation_id).maybe_single().execute()
        if convo is None or not convo.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        conversation_id = req.conversation_id
        db.table("conversations").update({"label_ids": labels}).eq("id", conversation_id).execute()
    else:
        conversation_id = (
            db.table("conversations")
            .insert({"user_id": user.id, "title": req.question[:80], "label_ids": labels})
            .execute()
            .data[0]["id"]
        )

    history = (
        db.table("messages").select("role,content").eq("conversation_id", conversation_id).order("created_at").execute().data
    )
    db.table("messages").insert({"conversation_id": conversation_id, "role": "user", "content": req.question}).execute()

    def events():
        yield _sse({"type": "conversation", "conversation_id": conversation_id})
        try:
            for event in pipeline.run(db, req.question, labels, history):
                if event["type"] == "final":
                    event["message_id"] = _persist(user, conversation_id, req.question, labels, event)
                    event.pop("trace", None)
                yield _sse(event)
        except RefusalError:
            yield _sse({"type": "error", "message": "The assistant declined to answer this request."})
        except LLMOutputError:
            log.exception("model returned unusable output")
            yield _sse({"type": "error", "message": "The language model returned an unusable response. Please try again."})
        except Exception:
            log.exception("chat pipeline failed")
            yield _sse({"type": "error", "message": "Something went wrong while answering. Please try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _persist(user: CurrentUser, conversation_id: str, question: str, labels: list[str], final: dict) -> str | None:
    db = user.db
    try:
        message_id = (
            db.table("messages")
            .insert(
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": final["answer"],
                    "citations": final["citations"],
                    "eval": final["eval"],
                }
            )
            .execute()
            .data[0]["id"]
        )
        row = {
            "user_id": user.id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "question": question,
            "label_ids": labels,
            "plan": final["plan"],
            "retrieved_chunk_ids": final["retrieved_chunk_ids"],
            "grounded_score": final["eval"].get("grounded_score"),
            "verdict": final["eval"].get("verdict"),
            "regenerated": final["regenerated"],
            "latency_ms": final["latency_ms"],
            "input_tokens": final["usage"]["input_tokens"],
            "output_tokens": final["usage"]["output_tokens"],
        }
        trace = {"retrieved": final["trace"]["retrieved"], "first_draft": final["trace"]["first_draft"]}
        try:
            db.table("query_logs").insert({**row, **trace}).execute()
        except APIError:
            # Database without migration 0004 (no trace columns): keep the log, drop the trace.
            log.warning("query_logs has no trace columns; run supabase/migrations/0004_query_trace.sql")
            db.table("query_logs").insert(row).execute()
        db.table("conversations").update({"label_ids": labels}).eq("id", conversation_id).execute()
        return message_id
    except Exception:
        log.exception("failed to persist answer")
        return None


@router.get("/conversations")
def list_conversations(user: CurrentUser = Depends(get_current_user)):
    return (
        user.db.table("conversations")
        .select("id,title,label_ids,updated_at")
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
        .data
    )


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: CurrentUser = Depends(get_current_user)):
    convo = user.db.table("conversations").select("*").eq("id", conversation_id).maybe_single().execute()
    if convo is None or not convo.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    messages = (
        user.db.table("messages")
        .select("id,role,content,citations,eval,feedback,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
        .data
    )
    return {**convo.data, "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: CurrentUser = Depends(get_current_user)):
    user.db.table("conversations").delete().eq("id", conversation_id).execute()


@router.post("/messages/{message_id}/feedback", status_code=204)
def message_feedback(message_id: str, body: Feedback, user: CurrentUser = Depends(get_current_user)):
    result = (
        user.db.table("messages")
        .update({"feedback": body.value, "feedback_note": body.note})
        .eq("id", message_id)
        .eq("role", "assistant")
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
