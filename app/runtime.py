from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from app.api.schemas.events import ActionData
from app.api.schemas.events import CommentActionPayload
from app.api.schemas.events import LikeActionPayload
from app.api.schemas.events import NoopActionPayload
from app.api.schemas.events import PostActionPayload
from app.api.schemas.events import RepostActionPayload
from app.domain.action_types import ActionType

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - depends on optional dependency
    ChatOpenAI = None  # type: ignore[assignment]


class AnimaState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _passthrough_node(_: AnimaState) -> dict[str, Any]:
    return {}


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


_ACTION_TOOLS = [
    post_action,
    like_action,
    comment_action,
    repost_action,
    noop_action,
]


memory = MemorySaver()
_graph_builder = StateGraph(AnimaState)
_graph_builder.add_node("passthrough", _passthrough_node)
_graph_builder.add_edge(START, "passthrough")
_graph_builder.add_edge("passthrough", END)
anima_app = _graph_builder.compile(checkpointer=memory)

def _build_model():
    if ChatOpenAI is None:
        raise RuntimeError("langchain_openai is not installed.")

    api_key = os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is not set.")

    model = ChatOpenAI(
        model=os.getenv("MOONSHOT_MODEL", "kimi-k2-turbo-preview"),
        api_key=api_key,
        base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
        temperature=float(os.getenv("MOONSHOT_TEMPERATURE", "0.6")),
    )
    return model.bind_tools(_ACTION_TOOLS, tool_choice="required")


_action_model = None


def _resolve_system_prompt(thread_id: str) -> str:
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint = memory.get_tuple(config)
    if checkpoint is None:
        raise RuntimeError(f"Agent profile is missing for thread_id={thread_id}.")

    messages = checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
    for message in reversed(messages):
        if isinstance(message, SystemMessage):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content

    raise RuntimeError(f"Agent profile is missing for thread_id={thread_id}.")


def infer_action(*, thread_id: str, event_5w: dict[str, Any]) -> ActionData:
    global _action_model
    if _action_model is None:
        _action_model = _build_model()

    system_prompt = _resolve_system_prompt(thread_id)
    input_text = json.dumps(event_5w, ensure_ascii=False)
    print(f"[runtime] Starting action inference thread_id={thread_id} event_5w={input_text}")
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=input_text),
    ]
    config = {"configurable": {"thread_id": thread_id}}

    ai_msg = _action_model.invoke(messages, config=config)
    raw_content = getattr(ai_msg, "content", ai_msg)
    tool_calls = getattr(ai_msg, "tool_calls", None)
    print(
        f"[runtime] Raw model response thread_id={thread_id} "
        f"raw={json.dumps(raw_content, ensure_ascii=False, default=str)}"
    )
    print(
        f"[runtime] Tool calls thread_id={thread_id} "
        f"tool_calls={json.dumps(tool_calls, ensure_ascii=False, default=str)}"
    )
    if not tool_calls:
        raise RuntimeError("Model did not return any tool call.")

    tool_call = tool_calls[0]
    tool_name = tool_call.get("name")
    args = tool_call.get("args", {})
    if isinstance(args, str):
        args = json.loads(args)
    if not isinstance(args, dict):
        raise RuntimeError("Tool call args format is invalid.")

    if tool_name == ActionType.POST.value:
        action = ActionData(type=ActionType.POST, post=PostActionPayload(**args))
    elif tool_name == ActionType.LIKE.value:
        action = ActionData(type=ActionType.LIKE, like=LikeActionPayload(**args))
    elif tool_name == ActionType.COMMENT.value:
        action = ActionData(type=ActionType.COMMENT, comment=CommentActionPayload(**args))
    elif tool_name == ActionType.REPOST.value:
        action = ActionData(type=ActionType.REPOST, repost=RepostActionPayload(**args))
    elif tool_name == ActionType.NOOP.value:
        action = ActionData(type=ActionType.NOOP, noop=NoopActionPayload(**args))
    else:
        raise RuntimeError(f"Unsupported tool action: {tool_name}")

    print(
        f"[runtime] Action inference succeeded thread_id={thread_id} "
        f"decision={action.model_dump_json(ensure_ascii=False)}"
    )

    anima_app.update_state(config, {"messages": [HumanMessage(content=input_text)]})
    anima_app.update_state(
        config,
        {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {"tool_name": tool_name, "args": args},
                        ensure_ascii=False,
                    )
                )
            ]
        },
    )
    return action
