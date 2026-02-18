from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class PostLikeItem(BaseModel):
    user_id: str
    liked_at: str


class PostCommentItem(BaseModel):
    comment_id: str
    user_id: str
    content: str
    created_at: str


class PostItem(BaseModel):
    post_id: str
    author_id: str
    content: str
    likes: list[PostLikeItem] = Field(default_factory=list)
    comments: list[PostCommentItem] = Field(default_factory=list)
    repost_count: int = 0
    repost_of_post_id: str | None = None
    created_at: str

    @staticmethod
    def new(
        *,
        author_id: str,
        content: str,
        repost_of_post_id: str | None = None,
    ) -> "PostItem":
        return PostItem(
            post_id=str(uuid4()),
            author_id=author_id,
            content=content,
            repost_of_post_id=repost_of_post_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
