from __future__ import annotations

from fastapi import APIRouter, status
from fastapi import Path
from pydantic import BaseModel, Field

from app.api.schemas.response import APIResponse
from app.api.schemas.social_dynamics import SessionSocialDynamicsData
from app.services.neo4j_event_store import get_neo4j_driver
from app.services.social_dynamics_service import SocialDynamicsService

router = APIRouter()
_SOCIAL_DYNAMICS_SERVICE: SocialDynamicsService | None = None


def _get_social_dynamics_service() -> SocialDynamicsService:
    global _SOCIAL_DYNAMICS_SERVICE
    if _SOCIAL_DYNAMICS_SERVICE is None:
        _SOCIAL_DYNAMICS_SERVICE = SocialDynamicsService(get_neo4j_driver())
    return _SOCIAL_DYNAMICS_SERVICE


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


@router.get(
    "/sessions/{session_id}",
    response_model=APIResponse[SessionSocialDynamicsData],
    status_code=status.HTTP_200_OK,
)
def get_session_social_dynamics(
    session_id: str = Path(min_length=1),
) -> APIResponse[SessionSocialDynamicsData]:
    """获取指定 Session 的全部社交动态（帖子/评论/点赞）。"""

    data = _get_social_dynamics_service().list_session_social_dynamics(session_id)
    return APIResponse[SessionSocialDynamicsData].success(
        data=data,
        message="social dynamics fetched",
    )
