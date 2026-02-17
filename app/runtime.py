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

from app.api.schemas.events import ActionData
from app.api.schemas.events import ActionDecision

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - depends on optional dependency
    ChatOpenAI = None  # type: ignore[assignment]


class AnimaState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _passthrough_node(_: AnimaState) -> dict[str, Any]:
    return {}


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
    return model.with_structured_output(
        ActionDecision,
        method="function_calling",
        include_raw=True,
    )


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

    result = _action_model.invoke(messages, config=config)
    if not isinstance(result, dict):
        raise RuntimeError("Structured output result format is invalid.")

    raw_msg = result.get("raw")
    parsed = result.get("parsed")
    parsing_error = result.get("parsing_error")
    raw_content = getattr(raw_msg, "content", raw_msg)
    print(
        f"[runtime] Raw model response thread_id={thread_id} "
        f"raw={json.dumps(raw_content, ensure_ascii=False, default=str)}"
    )
    if parsing_error is not None:
        raise RuntimeError(f"Structured parsing failed: {parsing_error}")
    if not isinstance(parsed, ActionDecision):
        raise RuntimeError("Model did not return parsed ActionDecision.")

    action = parsed.action
    print(
        f"[runtime] Action inference succeeded thread_id={thread_id} "
        f"decision={parsed.model_dump_json(ensure_ascii=False)}"
    )

    anima_app.update_state(config, {"messages": [HumanMessage(content=input_text)]})
    anima_app.update_state(
        config,
        {"messages": [AIMessage(content=parsed.model_dump_json(ensure_ascii=False))]},
    )
    return action
