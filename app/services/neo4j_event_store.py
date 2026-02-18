from __future__ import annotations

import json
import os
from threading import Lock

from app.api.schemas.events import EventRequest

try:
    from langchain_neo4j import Neo4jGraph
except ImportError:  # pragma: no cover - optional dependency
    Neo4jGraph = None  # type: ignore[assignment]


_GRAPH_LOCK = Lock()
_GRAPH: Neo4jGraph | None = None


def _json_string(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _resolve_location_fields(entity_location) -> tuple[str | None, str | None, float | None, float | None, float | None]:
    if entity_location is None:
        return None, None, None, None, None
    x, y, z = entity_location.coordinates
    return entity_location.dimension, entity_location.biome, x, y, z


def _get_graph() -> Neo4jGraph:
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH

    if Neo4jGraph is None:
        raise RuntimeError("langchain-neo4j is not installed. Please install langchain-neo4j and neo4j.")

    url = os.getenv("NEO4J_URL")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE")
    if not url or not username or not password:
        raise RuntimeError("NEO4J_URL/NEO4J_USERNAME/NEO4J_PASSWORD must be set.")

    with _GRAPH_LOCK:
        if _GRAPH is None:
            kwargs = {
                "url": url,
                "username": username,
                "password": password,
                # We only execute writes here; disabling schema refresh avoids APOC requirement.
                "refresh_schema": False,
            }
            if database:
                kwargs["database"] = database
            _GRAPH = Neo4jGraph(**kwargs)

    return _GRAPH


def ingest_minecraft_event(payload: EventRequest) -> None:
    sub_dim, sub_biome, sub_x, sub_y, sub_z = _resolve_location_fields(payload.subject.location)
    if payload.object is None:
        raise ValueError("EventRequest.object is required for subject->object graph insertion.")

    obj_dim, obj_biome, obj_x, obj_y, obj_z = _resolve_location_fields(payload.object.location)
    params = {
        "session_id": payload.session_id,
        "world_time": payload.world_time,
        "timestamp": payload.timestamp,
        "verb": payload.action.verb,
        "action_details_json": _json_string(payload.action.details),
        "sub_id": payload.subject.entity_id,
        "sub_type": payload.subject.entity_type,
        "sub_name": payload.subject.name,
        "sub_state_json": _json_string(payload.subject.state),
        "sub_dim": sub_dim,
        "sub_biome": sub_biome,
        "sub_x": sub_x,
        "sub_y": sub_y,
        "sub_z": sub_z,
        "obj_id": payload.object.entity_id,
        "obj_type": payload.object.entity_type,
        "obj_name": payload.object.name,
        "obj_state_json": _json_string(payload.object.state),
        "obj_dim": obj_dim,
        "obj_biome": obj_biome,
        "obj_x": obj_x,
        "obj_y": obj_y,
        "obj_z": obj_z,
    }

    query = """
    // 主语节点：Entity
    MERGE (sub:Entity {session_id: $session_id, entity_id: $sub_id})
    SET sub.entity_type = $sub_type,
        sub.name = $sub_name,
        sub.last_state_json = $sub_state_json,
        sub.dimension = $sub_dim,
        sub.biome = $sub_biome,
        sub.x = $sub_x, sub.y = $sub_y, sub.z = $sub_z,
        sub.updated_at = $timestamp

    // 宾语节点：Entity
    MERGE (obj:Entity {session_id: $session_id, entity_id: $obj_id})
    SET obj.entity_type = $obj_type,
        obj.name = $obj_name,
        obj.last_state_json = $obj_state_json,
        obj.dimension = $obj_dim,
        obj.biome = $obj_biome,
        obj.x = $obj_x, obj.y = $obj_y, obj.z = $obj_z,
        obj.updated_at = $timestamp

    // 核心主线：主语 -> 宾语，关系只保留动词所需字段
    CREATE (sub)-[rel:INTERACTED_WITH]->(obj)
    SET rel.verb = $verb,
        rel.details = $action_details_json,
        rel.world_time = $world_time
    """

    graph = _get_graph()
    graph.query(query, params=params)
