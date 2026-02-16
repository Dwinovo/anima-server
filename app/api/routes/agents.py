from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from app.api.schemas.response import APIResponse
from app.runtime import anima_app, memory

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

    checkpoint = memory.get_tuple(config)
    if checkpoint is not None:
        response.status_code = status.HTTP_200_OK
        return APIResponse[AgentRegisterData].success(
            data=AgentRegisterData(
                status="existing",
                thread_id=thread_id,
            ),
            message="agent already exists",
        )

    sys_msg = SystemMessage(content=payload.profile)
    anima_app.update_state(config, {"messages": [sys_msg]})
    response.status_code = status.HTTP_201_CREATED
    return APIResponse[AgentRegisterData].success(
        data=AgentRegisterData(
            status="created",
            thread_id=thread_id,
        ),
        message="agent created",
    )
