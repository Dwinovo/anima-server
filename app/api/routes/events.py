from __future__ import annotations

import json

from fastapi import APIRouter

from app.api.schemas.events import EventResponse
from app.api.schemas.events import EventRequest
from app.api.schemas.response import APIResponse
from app.services.neo4j_event_store import ingest_minecraft_event

router = APIRouter()


@router.post("/events", response_model=APIResponse[EventResponse], status_code=201)
def process_event(payload: EventRequest) -> APIResponse[EventResponse]:
    # 入口日志：保留原始请求，便于排查上游事件字段问题。
    print(f"[events] Received /api/events payload: {json.dumps(payload.model_dump(), ensure_ascii=False)}")

    # source_thread_id 仅用于日志定位；当前阶段只接收并确认创建事件。
    session_id = payload.session_id
    source_thread_id = f"{session_id}:{payload.subject.entity_id}"

    print(
        "[events] Event create ack mode "
        f"session_id={session_id} source_thread_id={source_thread_id} "
        f"event={json.dumps(payload.model_dump(), ensure_ascii=False)}"
    )
    ingest_minecraft_event(payload)
    print(f"[events] Event persisted to Neo4j session_id={session_id} source_thread_id={source_thread_id}")

    response_payload = APIResponse[EventResponse].success(
        data=EventResponse(
            session_id=session_id,
        ),
        message="event created",
    )
    print(
        f"[events] Returning /api/events response source_thread_id={source_thread_id} "
        f"payload={json.dumps(response_payload.model_dump(), ensure_ascii=False)}"
    )
    return response_payload
