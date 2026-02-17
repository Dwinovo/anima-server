from __future__ import annotations

from langchain_core.tools import tool

from app.domain.action_types import ActionType


@tool(ActionType.POST.value)
def post_action(
    content: str,
) -> str:
    """Create a new post."""
    return "ok"


@tool(ActionType.LIKE.value)
def like_action(target_post_id: str) -> str:
    """Like an existing post by id."""
    return "ok"


@tool(ActionType.COMMENT.value)
def comment_action(target_post_id: str, content: str) -> str:
    """Comment on an existing post by id."""
    return "ok"


@tool(ActionType.REPOST.value)
def repost_action(target_post_id: str, comment: str = "") -> str:
    """Repost an existing post by id."""
    return "ok"


@tool(ActionType.NOOP.value)
def noop_action(reason: str) -> str:
    """Do nothing for this event."""
    return "ok"


ACTION_TOOLS = [
    post_action,
    like_action,
    comment_action,
    repost_action,
    noop_action,
]
