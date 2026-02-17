from __future__ import annotations

import json

from fastapi import APIRouter

import app.runtime as runtime
from app.api.schemas.events import EventPayload
from app.api.schemas.events import EventProcessData
from app.api.schemas.response import APIResponse
from app.services.action_executor import apply_action

router = APIRouter()


@router.post("/events", response_model=APIResponse[EventProcessData])
def process_event(payload: EventPayload) -> APIResponse[EventProcessData]:
    print(f"[events] Received /api/events payload: {json.dumps(payload.model_dump(), ensure_ascii=False)}")

    session_id = payload.meta.session_id
    thread_id = f"{session_id}:{payload.who.entity_uuid}"

    event_5w = {
        "meta": payload.meta.model_dump(),
        "when": payload.when,
        "where": payload.where,
        "who": payload.who.model_dump(),
        "event": payload.event.model_dump(),
    }
    print(
        "[events] Processing event "
        f"session_id={session_id} thread_id={thread_id} "
        f"event_5w={json.dumps(event_5w, ensure_ascii=False)}"
    )

    action = runtime.infer_action(thread_id=thread_id, event_5w=event_5w)
    print(
        f"[events] Inferred action thread_id={thread_id} "
        f"action={json.dumps(action.model_dump(), ensure_ascii=False)}"
    )
    posts = apply_action(session_id=session_id, actor_id=payload.who.entity_uuid, action=action)
    print(
        f"[events] Updated posts session_id={session_id} total_posts={len(posts)} "
        f"posts={json.dumps([post.model_dump() for post in posts], ensure_ascii=False)}"
    )

    response_payload = APIResponse[EventProcessData].success(
        data=EventProcessData(posts=posts),
        message="Event processed",
    )
    print(
        f"[events] Returning /api/events response thread_id={thread_id} "
        f"payload={json.dumps(response_payload.model_dump(), ensure_ascii=False)}"
    )
    return response_payload
