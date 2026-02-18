from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import model_validator

from app.domain.action_types import ActionType


class PostActionPayload(BaseModel):
    content: str = Field(min_length=1)


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
    type: ActionType
    post: PostActionPayload | None = None
    like: LikeActionPayload | None = None
    comment: CommentActionPayload | None = None
    repost: RepostActionPayload | None = None
    noop: NoopActionPayload | None = None

    @model_validator(mode="after")
    def validate_by_type(self) -> "ActionData":
        action_type = self.type.value
        expected = {
            "post": self.post,
            "like": self.like,
            "comment": self.comment,
            "repost": self.repost,
            "noop": self.noop,
        }
        for key, value in expected.items():
            if key == action_type and value is None:
                raise ValueError(f"action.{key} is required when type={action_type}")
            if key != action_type and value is not None:
                raise ValueError(f"action.{key} must be null when type={action_type}")
        return self
