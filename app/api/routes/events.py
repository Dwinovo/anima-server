from __future__ import annotations

import json
from threading import Lock

from fastapi import APIRouter

import app.runtime as runtime
from app.api.schemas.events import ActionData
from app.api.schemas.events import EventPayload
from app.api.schemas.events import EventProcessData
from app.api.schemas.events import PostItem
from app.api.schemas.response import APIResponse

router = APIRouter()
_POSTS_BY_SESSION: dict[str, list[PostItem]] = {}
_POSTS_LOCK = Lock()


def _apply_action(session_id: str, actor_id: str, action: ActionData) -> list[PostItem]:
    with _POSTS_LOCK:
        posts = _POSTS_BY_SESSION.setdefault(session_id, [])

        if action.type == "post" and action.post is not None:
            posts.append(
                PostItem.new(
                    author_id=actor_id,
                    content=action.post.content,
                    media=action.post.media,
                    visibility=action.post.visibility,
                )
            )
        elif action.type == "like" and action.like is not None:
            for idx, item in enumerate(posts):
                if item.post_id == action.like.target_post_id:
                    posts[idx] = item.model_copy(update={"like_count": item.like_count + 1})
                    break
        elif action.type == "comment" and action.comment is not None:
            for idx, item in enumerate(posts):
                if item.post_id == action.comment.target_post_id:
                    posts[idx] = item.model_copy(update={"comment_count": item.comment_count + 1})
                    break
        elif action.type == "repost" and action.repost is not None:
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


@router.post("/events", response_model=APIResponse[EventProcessData])
def process_event(payload: EventPayload) -> APIResponse[EventProcessData]:
    print(f"[events] Received /api/events payload: {json.dumps(payload.model_dump(), ensure_ascii=False)}")

    session_id = payload.meta.session_id
    thread_id = f"{session_id}:{payload.who.entity_uuid}"

    event_5w = {
        "meta": payload.meta.model_dump(),
        "when": payload.when,
        "where": payload.where,
        "who": payload.who.model_dump(),
        "event": payload.event.model_dump(),
    }
    print(
        "[events] Processing event "
        f"session_id={session_id} thread_id={thread_id} "
        f"event_5w={json.dumps(event_5w, ensure_ascii=False)}"
    )

    action = runtime.infer_action(thread_id=thread_id, event_5w=event_5w)
    print(
        f"[events] Inferred action thread_id={thread_id} "
        f"action={json.dumps(action.model_dump(), ensure_ascii=False)}"
    )
    posts = _apply_action(session_id=session_id, actor_id=payload.who.entity_uuid, action=action)
    print(
        f"[events] Updated posts session_id={session_id} total_posts={len(posts)} "
        f"posts={json.dumps([post.model_dump() for post in posts], ensure_ascii=False)}"
    )

    response_payload = APIResponse[EventProcessData].success(
        data=EventProcessData(posts=posts),
        message="Event processed",
    )
    print(
        f"[events] Returning /api/events response thread_id={thread_id} "
        f"payload={json.dumps(response_payload.model_dump(), ensure_ascii=False)}"
    )
    return response_payload
