from __future__ import annotations

import json

from fastapi import APIRouter

import app.runtime as runtime
from app.api.schemas.events import EventPayload
from app.api.schemas.events import EventProcessData
from app.api.schemas.response import APIResponse
from app.services.event_workflow import run_event_workflow

router = APIRouter()


@router.post("/events", response_model=APIResponse[EventProcessData])
def process_event(payload: EventPayload) -> APIResponse[EventProcessData]:
    # 入口日志：保留原始请求，便于排查上游事件字段问题。
    print(f"[events] Received /api/events payload: {json.dumps(payload.model_dump(), ensure_ascii=False)}")

    # source_thread_id 代表事件来源实体；target_thread_ids 代表本次要参与决策的 Agent 集合。
    session_id = payload.meta.session_id
    source_thread_id = f"{session_id}:{payload.who.entity_uuid}"
    target_thread_ids = runtime.list_thread_ids_by_session(session_id)

    print(
        "[events] Processing event "
        f"session_id={session_id} target_thread_ids={target_thread_ids} "
        f"event={json.dumps(payload.model_dump(exclude={'who': {'perspective'}}), ensure_ascii=False)}"
    )

    # 用图编排执行：infer 节点并发，动作提交节点串行，兼顾吞吐和状态一致性。
    posts = run_event_workflow(
        session_id=session_id,
        event_payload=payload,
        target_thread_ids=target_thread_ids,
    )

    print(
        f"[events] Updated posts session_id={session_id} total_posts={len(posts)} "
        f"posts={json.dumps([post.model_dump() for post in posts], ensure_ascii=False)}"
    )

    response_payload = APIResponse[EventProcessData].success(
        data=EventProcessData(posts=posts),
        message="Event processed",
    )
    print(
        f"[events] Returning /api/events response source_thread_id={source_thread_id} "
        f"payload={json.dumps(response_payload.model_dump(), ensure_ascii=False)}"
    )
    return response_payload
