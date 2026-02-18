from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from app.api.schemas.actions import ActionData
from app.api.schemas.posts import PostCommentItem
from app.api.schemas.posts import PostLikeItem
from app.api.schemas.posts import PostItem
from app.domain.action_types import ActionType

_POSTS_BY_SESSION: dict[str, list[PostItem]] = {}
_POSTS_LOCK = Lock()


def clear_all_posts() -> None:
    with _POSTS_LOCK:
        _POSTS_BY_SESSION.clear()


def get_posts(session_id: str) -> list[PostItem]:
    # 读取会话级帖子快照，供本轮推理作为“社交平台上下文”输入。
    with _POSTS_LOCK:
        posts = _POSTS_BY_SESSION.get(session_id, [])
        return [post.model_copy() for post in posts]


def apply_action(session_id: str, actor_id: str, action: ActionData) -> list[PostItem]:
    # 会话级帖子池，所有 Agent 在同一 session 下共享。
    with _POSTS_LOCK:
        posts = _POSTS_BY_SESSION.setdefault(session_id, [])

        if action.type == ActionType.POST and action.post is not None:
            # 发帖：直接追加新帖子。
            posts.append(
                PostItem.new(
                    author_id=actor_id,
                    content=action.post.content,
                )
            )
        elif action.type == ActionType.LIKE and action.like is not None:
            # 点赞：同一 user_id 对同一帖子只保留一次点赞记录。
            for idx, item in enumerate(posts):
                if item.post_id == action.like.target_post_id:
                    if any(like.user_id == actor_id for like in item.likes):
                        break
                    new_likes = [
                        *item.likes,
                        PostLikeItem(
                            user_id=actor_id,
                            liked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ),
                    ]
                    posts[idx] = item.model_copy(update={"likes": new_likes})
                    break
        elif action.type == ActionType.COMMENT and action.comment is not None:
            # 评论：保存评论明细，记录评论者和评论内容。
            for idx, item in enumerate(posts):
                if item.post_id == action.comment.target_post_id:
                    new_comments = [
                        *item.comments,
                        PostCommentItem(
                            comment_id=str(uuid4()),
                            user_id=actor_id,
                            content=action.comment.content,
                            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        ),
                    ]
                    posts[idx] = item.model_copy(update={"comments": new_comments})
                    break
        elif action.type == ActionType.REPOST and action.repost is not None:
            # 转发：先给原帖 repost_count +1，命中后再追加一条“转发帖”。
            target_exists = False
            for idx, item in enumerate(posts):
                if item.post_id == action.repost.target_post_id:
                    posts[idx] = item.model_copy(update={"repost_count": item.repost_count + 1})
                    target_exists = True
                    break
            if target_exists:
                posts.append(
                    PostItem.new(
                        author_id=actor_id,
                        content=action.repost.comment,
                        repost_of_post_id=action.repost.target_post_id,
                    )
                )

        return [post.model_copy() for post in posts]
