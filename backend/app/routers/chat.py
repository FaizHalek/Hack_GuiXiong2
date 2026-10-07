import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents import pipeline
from app.db import connect, fetch_all, fetch_one, new_id, now, to_json
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


def _own_conversation(conn, user: CurrentUser, conversation_id: str) -> dict:
    convo = fetch_one(conn, "select * from conversations where id = ? and user_id = ?", (conversation_id, user.id))
    if convo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return convo


@router.post("/chat")
def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user)):
    labels = authorised_labels(req.label_ids, user)
    if not labels:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to any of the selected collections")

    with connect() as conn:
        stamp = now()
        if req.conversation_id:
            conversation_id = _own_conversation(conn, user, req.conversation_id)["id"]
            conn.execute(
                "update conversations set label_ids = ?, updated_at = ? where id = ?", (to_json(labels), stamp, conversation_id)
            )
        else:
            conversation_id = new_id()
            conn.execute(
                "insert into conversations (id, user_id, title, label_ids, created_at, updated_at) values (?, ?, ?, ?, ?, ?)",
                (conversation_id, user.id, req.question[:80], to_json(labels), stamp, stamp),
            )
        history = fetch_all(
            conn,
            "select role, content from messages where conversation_id = ? order by created_at, rowid",
            (conversation_id,),
        )
        conn.execute(
            "insert into messages (id, conversation_id, role, content, created_at) values (?, ?, 'user', ?, ?)",
            (new_id(), conversation_id, req.question, stamp),
        )

    def events():
        yield _sse({"type": "conversation", "conversation_id": conversation_id})
        try:
            for event in pipeline.run(req.question, labels, history):
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
    try:
        message_id = new_id()
        stamp = now()
        with connect() as conn:
            conn.execute(
                "insert into messages (id, conversation_id, role, content, citations, eval, created_at)"
                " values (?, ?, 'assistant', ?, ?, ?, ?)",
                (message_id, conversation_id, final["answer"], to_json(final["citations"]), to_json(final["eval"]), stamp),
            )
            conn.execute(
                "insert into query_logs (id, user_id, conversation_id, message_id, question, label_ids, plan,"
                " retrieved_chunk_ids, retrieved, first_draft, grounded_score, verdict, regenerated, latency_ms,"
                " input_tokens, output_tokens, created_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id(),
                    user.id,
                    conversation_id,
                    message_id,
                    question,
                    to_json(labels),
                    to_json(final["plan"]),
                    to_json(final["retrieved_chunk_ids"]),
                    to_json(final["trace"]["retrieved"]),
                    to_json(final["trace"]["first_draft"]) if final["trace"]["first_draft"] else None,
                    final["eval"].get("grounded_score"),
                    final["eval"].get("verdict"),
                    int(final["regenerated"]),
                    final["latency_ms"],
                    final["usage"]["input_tokens"],
                    final["usage"]["output_tokens"],
                    stamp,
                ),
            )
            conn.execute("update conversations set updated_at = ? where id = ?", (stamp, conversation_id))
        return message_id
    except Exception:
        log.exception("failed to persist answer")
        return None


@router.get("/conversations")
def list_conversations(user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        return fetch_all(
            conn,
            "select id, title, label_ids, updated_at from conversations where user_id = ? order by updated_at desc limit 50",
            (user.id,),
        )


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        convo = _own_conversation(conn, user, conversation_id)
        messages = fetch_all(
            conn,
            "select id, role, content, citations, eval, feedback, created_at from messages"
            " where conversation_id = ? order by created_at, rowid",
            (conversation_id,),
        )
    return {**convo, "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        conn.execute("delete from conversations where id = ? and user_id = ?", (conversation_id, user.id))


@router.post("/messages/{message_id}/feedback", status_code=204)
def message_feedback(message_id: str, body: Feedback, user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        result = conn.execute(
            "update messages set feedback = ?, feedback_note = ? where id = ? and role = 'assistant'"
            " and conversation_id in (select id from conversations where user_id = ?)",
            (body.value, body.note, message_id, user.id),
        )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
