from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.schemas.response import APIResponse

router = APIRouter()


class SessionCreateRequest(BaseModel):
    anima_session_id: str = Field(min_length=1)
    seed: str = Field(min_length=1)


class SessionCreateData(BaseModel):
    status: str = "created"
    session_id: str


@router.post("/sessions", response_model=APIResponse[SessionCreateData], status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreateRequest) -> APIResponse[SessionCreateData]:
    
    return APIResponse[SessionCreateData].success(
        data=SessionCreateData(
            session_id=payload.anima_session_id,
        ),
        message="session created",
    )
