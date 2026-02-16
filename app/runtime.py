from __future__ import annotations

from typing import Any

from langchain_core.messages import AnyMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict


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
