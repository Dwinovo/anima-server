from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionSocialDynamicItem(BaseModel):
    activity_id: str
    activity_type: Literal["post", "comment", "like"]
    actor_id: str
    actor_name: str
    post_id: str
    target_post_id: str | None = None
    content: str | None = None
    timestamp: str


class SessionSocialDynamicsData(BaseModel):
    session_id: str
    total: int
    items: list[SessionSocialDynamicItem] = Field(default_factory=list)
