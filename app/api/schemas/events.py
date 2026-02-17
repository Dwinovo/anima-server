from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator


class MetaPayload(BaseModel):
    session_id: str = Field(min_length=1)


class EventData(BaseModel):
    subject: dict[str, Any]
    action: str = Field(min_length=1)
    object: dict[str, Any]
    details: dict[str, Any]
    raw_text: str = Field(min_length=1)


class WhoPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    entity_uuid: str = Field(min_length=1)


class EventPayload(BaseModel):
    meta: MetaPayload
    when: dict[str, Any]
    where: dict[str, Any]
    who: WhoPayload
    event: EventData


class PostActionPayload(BaseModel):
    content: str = Field(min_length=1)
    media: list[str] = Field(default_factory=list)
    visibility: Literal["public", "followers", "private"] = "public"


class LikeActionPayload(BaseModel):
    target_post_id: str = Field(min_length=1)


class CommentActionPayload(BaseModel):
    target_post_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class RepostActionPayload(BaseModel):
    target_post_id: str = Field(min_length=1)
    comment: str = ""


class NoopActionPayload(BaseModel):
    reason: str = Field(min_length=1)


class ActionData(BaseModel):
    type: Literal["post", "like", "comment", "repost", "noop"]
    post: PostActionPayload | None = None
    like: LikeActionPayload | None = None
    comment: CommentActionPayload | None = None
    repost: RepostActionPayload | None = None
    noop: NoopActionPayload | None = None

    @model_validator(mode="after")
    def validate_by_type(self) -> "ActionData":
        expected = {
            "post": self.post,
            "like": self.like,
            "comment": self.comment,
            "repost": self.repost,
            "noop": self.noop,
        }
        for key, value in expected.items():
            if key == self.type and value is None:
                raise ValueError(f"action.{key} is required when type={self.type}")
            if key != self.type and value is not None:
                raise ValueError(f"action.{key} must be null when type={self.type}")
        return self


class ActionDecision(BaseModel):
    action: ActionData


class PostItem(BaseModel):
    post_id: str
    author_id: str
    content: str
    media: list[str] = Field(default_factory=list)
    visibility: Literal["public", "followers", "private"] = "public"
    like_count: int = 0
    comment_count: int = 0
    repost_count: int = 0
    repost_of_post_id: str | None = None
    created_at: str

    @staticmethod
    def new(
        *,
        author_id: str,
        content: str,
        media: list[str] | None = None,
        visibility: Literal["public", "followers", "private"] = "public",
        repost_of_post_id: str | None = None,
    ) -> "PostItem":
        return PostItem(
            post_id=str(uuid4()),
            author_id=author_id,
            content=content,
            media=media or [],
            visibility=visibility,
            repost_of_post_id=repost_of_post_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


class EventProcessData(BaseModel):
    posts: list[PostItem]
