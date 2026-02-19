from __future__ import annotations

from datetime import datetime, timezone
import os
from uuid import uuid4

from neo4j import Driver


class SocialGraphRepository:
    """社交图谱写入仓储。

    约束：
    - 所有查询均使用参数化，避免 Cypher 注入；
    - 所有 MATCH 都带 session_id，确保沙盒隔离；
    - 只处理社交层（帖子/评论/点赞），不处理物理事件层。
    """

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database if database is not None else os.getenv("NEO4J_DATABASE")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create_post(self, session_id: str, agent_uuid: str, content: str) -> str:
        """创建 ORIGINAL 帖子，并建立 (Entity)-[:POSTED]->(SocialPost)。"""

        post_id = str(uuid4())
        timestamp = self._now_iso()
        query = """
        MERGE (actor:Entity {session_id: $session_id, entity_id: $agent_uuid})
        CREATE (post:SocialPost {
            post_id: $post_id,
            session_id: $session_id,
            type: 'ORIGINAL',
            content: $content,
            timestamp: $timestamp
        })
        MERGE (actor)-[:POSTED]->(post)
        RETURN post.post_id AS post_id
        """
        params = {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "post_id": post_id,
            "content": content,
            "timestamp": timestamp,
        }
        with self._driver.session(database=self._database) as session:
            record = session.execute_write(lambda tx: tx.run(query, params).single())
        if record is None:
            raise RuntimeError("Failed to create social post.")
        return str(record["post_id"])

    def create_comment(
        self,
        session_id: str,
        agent_uuid: str,
        target_post_id: str,
        content: str,
    ) -> str:
        """创建 COMMENT 帖子，建立 POSTED 与 REPLIED_TO 拓扑。"""

        post_id = str(uuid4())
        timestamp = self._now_iso()
        query = """
        MATCH (parent:SocialPost {session_id: $session_id, post_id: $target_post_id})
        MERGE (actor:Entity {session_id: $session_id, entity_id: $agent_uuid})
        CREATE (comment:SocialPost {
            post_id: $post_id,
            session_id: $session_id,
            type: 'COMMENT',
            content: $content,
            timestamp: $timestamp
        })
        MERGE (actor)-[:POSTED]->(comment)
        MERGE (comment)-[:REPLIED_TO]->(parent)
        RETURN comment.post_id AS post_id
        """
        params = {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "target_post_id": target_post_id,
            "post_id": post_id,
            "content": content,
            "timestamp": timestamp,
        }
        with self._driver.session(database=self._database) as session:
            record = session.execute_write(lambda tx: tx.run(query, params).single())
        if record is None:
            raise ValueError(
                f"Target post not found in session: target_post_id={target_post_id!r}"
            )
        return str(record["post_id"])

    def like_post(self, session_id: str, agent_uuid: str, target_post_id: str) -> bool:
        """点赞帖子；同一 Agent 对同一帖子只保留一个 LIKED 关系。"""

        timestamp = self._now_iso()
        query = """
        MATCH (actor:Entity {session_id: $session_id, entity_id: $agent_uuid})
        MATCH (post:SocialPost {session_id: $session_id, post_id: $target_post_id})
        MERGE (actor)-[liked:LIKED]->(post)
        ON CREATE SET liked.timestamp = $timestamp
        RETURN liked.timestamp = $timestamp AS created
        """
        params = {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "target_post_id": target_post_id,
            "timestamp": timestamp,
        }
        with self._driver.session(database=self._database) as session:
            record = session.execute_write(lambda tx: tx.run(query, params).single())
        if record is None:
            raise ValueError(
                f"Target post or actor not found in session: target_post_id={target_post_id!r}"
            )
        return bool(record["created"])
