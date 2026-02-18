from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from app.api.schemas.actions import ActionData
from app.api.schemas.actions import CommentActionPayload
from app.api.schemas.actions import LikeActionPayload
from app.api.schemas.actions import NoopActionPayload
from app.api.schemas.actions import PostActionPayload
from app.api.schemas.actions import RepostActionPayload
from app.api.schemas.events import EventRequest
from app.api.schemas.posts import PostItem
from app.domain.action_tools import ACTION_TOOLS
from app.domain.action_types import ActionType

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - depends on optional dependency
    ChatOpenAI = None  # type: ignore[assignment]


class AnimaState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _passthrough_node(_: AnimaState) -> dict[str, Any]:
    return {}


# LangGraph 内存型 checkpointer：按 thread_id 维护每个 Agent 的消息状态。
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
    return model.bind_tools(ACTION_TOOLS, tool_choice="required")


_action_model = None


def _get_thread_messages(thread_id: str) -> list[AnyMessage]:
    """通过 LangGraph state API 读取指定 thread 的消息列表。"""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = anima_app.get_state(config)
    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    messages = values.get("messages", [])
    if isinstance(messages, list):
        return messages
    return []


def _resolve_history_messages(thread_id: str) -> list[AnyMessage]:
    """读取该 Agent 的历史 Human/AI 消息，作为下一次推理上下文。"""
    messages = _get_thread_messages(thread_id)
    # 历史窗口可配置；0 或负数表示不截断。
    history_limit = int(os.getenv("ANIMA_HISTORY_LIMIT", "20"))
    history_messages = [msg for msg in messages if isinstance(msg, (HumanMessage, AIMessage))]
    if history_limit <= 0:
        return history_messages
    return history_messages[-history_limit:]


def _resolve_system_prompt(thread_id: str) -> str:
    # 从该线程历史中反向查找最近一条 SystemMessage，作为当前推理的人设与规则基线。
    messages = _get_thread_messages(thread_id)
    for message in reversed(messages):
        if isinstance(message, SystemMessage):
            content = message.content
            if isinstance(content, str) and content.strip():
                return content

    raise RuntimeError(f"Agent profile is missing for thread_id={thread_id}.")


def list_thread_ids_by_session(session_id: str) -> list[str]:
    # 从 checkpoint 中枚举同一 session 下所有已注册 thread_id。
    # 注意：这里仍直接读取 checkpointer；若未来切换外部存储，可考虑单独维护索引表。
    prefix = f"{session_id}:"
    thread_ids: set[str] = set()

    for checkpoint in memory.list(None):
        configurable = checkpoint.config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id.startswith(prefix):
            thread_ids.add(thread_id)

    return sorted(thread_ids)


def infer_action(
    *,
    thread_id: str,
    event_payload: EventRequest,
    social_posts: list[PostItem],
) -> ActionData:
    global _action_model
    if _action_model is None:
        _action_model = _build_model()

    system_prompt = _resolve_system_prompt(thread_id)
    history_messages = _resolve_history_messages(thread_id)
    # 统一在 runtime 层完成事件序列化。
    current_event = event_payload.model_dump()
    # 给模型的当前输入：社交平台帖子快照 + 当前事件。
    inference_input = {
        "social_posts": [post.model_dump() for post in social_posts],
        "current_event": current_event,
    }
    inference_input_text = json.dumps(inference_input, ensure_ascii=False)
    print(f"[runtime] Starting action inference thread_id={thread_id} input={inference_input_text}")
    # 输入由四部分组成：系统提示词 + 历史事件/动作 + 社交平台帖子 + 当前事件。
    messages = [
        SystemMessage(content=system_prompt),
        # 带入该 Agent 过去的事件和动作，保证“记得发生过什么、做过什么”。
        *history_messages,
        HumanMessage(content=inference_input_text),
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

    # 解析首个 tool call 为动作结果；当前策略要求模型必须走工具调用。
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

    # 将本次“事件输入 + 动作输出”写回 thread 状态，供下次推理作为历史上下文。
    # 历史里仅保留当前事件，避免把整个平台帖子快照反复写入记忆导致上下文膨胀。
    anima_app.update_state(
        config,
        {"messages": [HumanMessage(content=json.dumps(current_event, ensure_ascii=False))]},
    )
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
