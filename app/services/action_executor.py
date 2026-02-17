from __future__ import annotations

from threading import Lock

from app.api.schemas.events import ActionData
from app.api.schemas.events import PostItem
from app.domain.action_types import ActionType

_POSTS_BY_SESSION: dict[str, list[PostItem]] = {}
_POSTS_LOCK = Lock()


def clear_all_posts() -> None:
    with _POSTS_LOCK:
        _POSTS_BY_SESSION.clear()


def apply_action(session_id: str, actor_id: str, action: ActionData) -> list[PostItem]:
    with _POSTS_LOCK:
        posts = _POSTS_BY_SESSION.setdefault(session_id, [])

        if action.type == ActionType.POST and action.post is not None:
            posts.append(
                PostItem.new(
                    author_id=actor_id,
                    content=action.post.content,
                )
            )
        elif action.type == ActionType.LIKE and action.like is not None:
            for idx, item in enumerate(posts):
                if item.post_id == action.like.target_post_id:
                    posts[idx] = item.model_copy(update={"like_count": item.like_count + 1})
                    break
        elif action.type == ActionType.COMMENT and action.comment is not None:
            for idx, item in enumerate(posts):
                if item.post_id == action.comment.target_post_id:
                    posts[idx] = item.model_copy(update={"comment_count": item.comment_count + 1})
                    break
        elif action.type == ActionType.REPOST and action.repost is not None:
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
