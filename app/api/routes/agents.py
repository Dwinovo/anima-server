from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from app.api.schemas.response import APIResponse
from app.prompts import render_agent_system_prompt
from app.runtime import anima_app

router = APIRouter()


class AgentRegisterRequest(BaseModel):
    session_id: str = Field(min_length=1)
    entity_uuid: str = Field(min_length=1)
    entity_type: str = Field(default="unknown", min_length=1)
    profile: str = Field(min_length=1)


class AgentRegisterData(BaseModel):
    status: str
    thread_id: str


@router.post(
    "/agents",
    response_model=APIResponse[AgentRegisterData],
    status_code=status.HTTP_201_CREATED,
)
def register_agent(
    payload: AgentRegisterRequest, response: Response
) -> APIResponse[AgentRegisterData]:
    if anima_app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="anima_app is not initialized.",
        )

    thread_id = f"{payload.session_id}:{payload.entity_uuid}"
    config = {"configurable": {"thread_id": thread_id}}

    # 幂等注册：若已有有效 system prompt，直接返回 existing。
    snapshot = anima_app.get_state(config)
    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    messages = values.get("messages", [])
    has_system_prompt = False
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, SystemMessage):
                content = msg.content
                if isinstance(content, str) and content.strip():
                    has_system_prompt = True
                    break

    if has_system_prompt:
        response.status_code = status.HTTP_200_OK
        return APIResponse[AgentRegisterData].success(
            data=AgentRegisterData(
                status="existing",
                thread_id=thread_id,
            ),
            message="agent already exists",
        )

    sys_msg = SystemMessage(
        # 注册时将平台规则、身份与人设渲染成统一 system prompt 写入线程状态。
        content=render_agent_system_prompt(
            session_id=payload.session_id,
            entity_uuid=payload.entity_uuid,
            entity_type=payload.entity_type,
            profile=payload.profile,
        )
    )
    anima_app.update_state(config, {"messages": [sys_msg]})
    response.status_code = status.HTTP_201_CREATED
    return APIResponse[AgentRegisterData].success(
        data=AgentRegisterData(
            status="created",
            thread_id=thread_id,
        ),
        message="agent created",
    )
