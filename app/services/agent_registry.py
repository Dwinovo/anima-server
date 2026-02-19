from __future__ import annotations

from threading import Lock

# 进程内注册表：按 session_id 维护当前已注册 Agent UUID 集合。
_AGENT_IDS_BY_SESSION: dict[str, set[str]] = {}
_REGISTRY_LOCK = Lock()


def remember_agent_id(session_id: str, agent_uuid: str) -> None:
    """记录已注册 Agent ID（幂等）。"""

    normalized_session = session_id.strip()
    normalized_agent = agent_uuid.strip()
    if not normalized_session or not normalized_agent:
        return

    with _REGISTRY_LOCK:
        agent_ids = _AGENT_IDS_BY_SESSION.setdefault(normalized_session, set())
        agent_ids.add(normalized_agent)


def list_registered_agent_ids(session_id: str) -> list[str]:
    """读取指定 Session 的已注册 Agent ID 列表（稳定排序）。"""

    normalized_session = session_id.strip()
    if not normalized_session:
        return []

    with _REGISTRY_LOCK:
        agent_ids = _AGENT_IDS_BY_SESSION.get(normalized_session, set()).copy()
    return sorted(agent_ids)


def clear_registered_agent_ids(*, session_id: str | None = None) -> None:
    """清理注册表（测试辅助函数）。"""

    with _REGISTRY_LOCK:
        if session_id is None:
            _AGENT_IDS_BY_SESSION.clear()
            return
        _AGENT_IDS_BY_SESSION.pop(session_id.strip(), None)
