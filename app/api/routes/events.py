from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, model_validator

import app.runtime as runtime
from app.api.schemas.response import APIResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class EventPayload(BaseModel):
    session_id: str = Field(min_length=1)
    when: dict[str, Any]
    where: dict[str, Any]
    who: dict[str, Any]
    event: dict[str, Any]

    @model_validator(mode="after")
    def validate_who_entity_uuid(self) -> "EventPayload":
        entity_uuid = self.who.get("entity_uuid")
        if not isinstance(entity_uuid, str) or not entity_uuid.strip():
            raise ValueError("who.entity_uuid is required and must be a non-empty string")
        return self


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _to_action_data(llm_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(llm_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"action": {"type": "chat", "content": llm_text}}


@router.post("/events", response_model=APIResponse[dict[str, Any]])
def process_event(payload: EventPayload) -> APIResponse[dict[str, Any]]:
    logger.info(
        "Received /api/events payload: %s",
        json.dumps(payload.model_dump(), ensure_ascii=False),
    )

    entity_uuid = payload.who["entity_uuid"]
    thread_id = f"{payload.session_id}:{entity_uuid}"
    config = {"configurable": {"thread_id": thread_id}}

    event_5w = {
        "when": payload.when,
        "where": payload.where,
        "who": payload.who,
        "event": payload.event,
    }
    human_msg = HumanMessage(content=json.dumps(event_5w, ensure_ascii=False))

    result = runtime.anima_app.invoke({"messages": [human_msg]}, config=config)
    messages = result.get("messages", [])
    if not messages:
        action_data = {"action": {"type": "chat", "content": ""}}
    else:
        llm_text = _message_content_to_text(messages[-1].content)
        action_data = _to_action_data(llm_text)

    return APIResponse[dict[str, Any]].success(
        data=action_data,
        message="Event processed",
    )
