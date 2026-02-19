from __future__ import annotations

import json
import os
from threading import Lock
from uuid import uuid4

from neo4j import Driver
from neo4j import GraphDatabase
from neo4j import NotificationMinimumSeverity

from app.api.schemas.events import EventRequest
from app.api.schemas.events import MinecraftEntity


# 进程内复用一个 Neo4j Driver，避免每次请求都重新建连。
_DRIVER_LOCK = Lock()
_DRIVER: Driver | None = None


def _escape_cypher_identifier(raw: str) -> str:
    """最小转义：仅处理反引号，其他字符（含冒号）保持原样。"""
    return raw.replace("`", "``")


def _snapshot_relationship_properties(entity: MinecraftEntity) -> dict[str, object]:
    """关系快照：仅存展开字段，不存 JSON 保底。"""
    dimension: str | None = None
    biome: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    if entity.location is not None:
        dimension = entity.location.dimension
        biome = entity.location.biome
        x, y, z = entity.location.coordinates

    return {
        "state_health": entity.state.health,
        "state_max_health": entity.state.max_health,
        "location_dimension": dimension,
        "location_biome": biome,
        "location_x": x,
        "location_y": y,
        "location_z": z,
    }


def _format_entity_display_name(name: str | None, entity_id: str) -> str:
    """统一实体显示名：`name#uuid前五位`。

    规则：
    - 若 name 为空，回退到 entity_id 作为名字部分；
    - uuid 前缀取 entity_id 的前 5 个字符（长度不足 5 则按实际长度）。
    """

    normalized_id = entity_id.strip() or "unknown"
    normalized_name = name.strip() if isinstance(name, str) else ""
    base_name = normalized_name or normalized_id
    return f"{base_name}#{normalized_id[:5]}"


def get_neo4j_driver() -> Driver:
    """返回全局 Neo4j Driver（懒加载 + 线程安全）。"""

    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER

    url = os.getenv("NEO4J_URL")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not url or not username or not password:
        raise RuntimeError("NEO4J_URL/NEO4J_USERNAME/NEO4J_PASSWORD must be set.")

    with _DRIVER_LOCK:
        if _DRIVER is None:
            _DRIVER = GraphDatabase.driver(
                url,
                auth=(username, password),
                # 关闭 DBMS notification，避免 deprecation/schema 提示刷屏。
                notifications_min_severity=NotificationMinimumSeverity.OFF,
            )
    return _DRIVER


def ingest_event_to_neo4j(driver: Driver, event: EventRequest) -> str:
    """把 EventRequest 写入 Neo4j（Event Node / Reification 模型）。

    图结构：
    - (sub:Entity)-[:INITIATED {snapshot...}]->(evt:Event)
    - (evt)-[:TARGETED {snapshot...}]->(obj:Entity)  # 当 object 存在
    """

    # 事件节点每次 CREATE，必须拥有独立 ID 以形成可追溯时序。
    event_id = str(uuid4())

    # Entity 动态子标签按 entity_type 原样使用（仅做反引号转义防止语法错误）。
    subject_label = _escape_cypher_identifier(event.subject.entity_type)
    object_label = _escape_cypher_identifier(event.object.entity_type) if event.object is not None else None

    query = f"""
    // Entity 节点只存稳定身份信息，不存瞬时状态（HP/坐标）
    MERGE (sub:Entity:`{subject_label}` {{session_id: $session_id, entity_id: $sub_id}})
    SET sub.name = $sub_name,
        sub.entity_type = $sub_type

    // 每次请求必须 CREATE 新事件节点，形成可追溯时间序列
    CREATE (evt:Event {{
        event_id: $event_id,
        session_id: $session_id,
        timestamp: $timestamp,
        world_time: $world_time,
        verb: $verb,
        details: $details
    }})

    // Subject -> Event：在 INITIATED 关系上保存发起者快照状态
    CREATE (sub)-[init:INITIATED]->(evt)
    SET init += $subject_snapshot
    """

    if event.object is not None and object_label is not None:
        query += f"""
        // Object 节点同样只维护稳定身份
        MERGE (obj:Entity:`{object_label}` {{session_id: $session_id, entity_id: $obj_id}})
        SET obj.name = $obj_name,
            obj.entity_type = $obj_type

        // Event -> Object：在 TARGETED 关系上保存承受者快照状态
        CREATE (evt)-[tgt:TARGETED]->(obj)
        SET tgt += $object_snapshot
        """

    # details 不展开，整段以 JSON 字符串存储。
    params: dict[str, object] = {
        "event_id": event_id,
        "session_id": event.session_id,
        "timestamp": event.timestamp,
        "world_time": event.world_time,
        "verb": event.action.verb,
        "details": json.dumps(event.action.details, ensure_ascii=False),
        "sub_id": event.subject.entity_id,
        "sub_name": _format_entity_display_name(
            event.subject.name,
            event.subject.entity_id,
        ),
        "sub_type": event.subject.entity_type,
        "subject_snapshot": _snapshot_relationship_properties(event.subject),
    }

    if event.object is not None:
        params.update(
            {
                "obj_id": event.object.entity_id,
                "obj_name": _format_entity_display_name(
                    event.object.name,
                    event.object.entity_id,
                ),
                "obj_type": event.object.entity_type,
                "object_snapshot": _snapshot_relationship_properties(event.object),
            }
        )

    # 支持多数据库部署；不配时使用 Neo4j 默认数据库。
    database = os.getenv("NEO4J_DATABASE")

    with driver.session(database=database) as session:
        # 所有写操作都放到 write transaction，保证失败时自动回滚。
        session.execute_write(lambda tx: tx.run(query, params).consume())

    return event_id
