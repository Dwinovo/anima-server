from __future__ import annotations

import os
from typing import Any

from neo4j import Driver

from app.api.schemas.social_dynamics import SessionSocialDynamicItem
from app.api.schemas.social_dynamics import SessionSocialDynamicsData


class SocialDynamicsService:
    """按 Session 聚合社交动态（帖子/评论/点赞），供前端直接渲染。"""

    _SESSION_SOCIAL_DYNAMICS_QUERY = """
    CALL {
      MATCH (actor:Entity {session_id: $session_id})-[:POSTED]->(post:SocialPost {session_id: $session_id})
      OPTIONAL MATCH (post)-[:REPLIED_TO]->(parent:SocialPost {session_id: $session_id})
      RETURN
        post.post_id AS activity_id,
        CASE WHEN post.type = 'COMMENT' THEN 'comment' ELSE 'post' END AS activity_type,
        actor.entity_id AS actor_id,
        coalesce(actor.name, actor.entity_id) AS actor_name,
        post.post_id AS post_id,
        CASE WHEN post.type = 'COMMENT' THEN parent.post_id ELSE NULL END AS target_post_id,
        post.content AS content,
        coalesce(post.timestamp, '') AS timestamp
      UNION ALL
      MATCH (actor:Entity {session_id: $session_id})-[liked:LIKED]->(post:SocialPost {session_id: $session_id})
      RETURN
        actor.entity_id + ':' + post.post_id + ':' + coalesce(liked.timestamp, '') AS activity_id,
        'like' AS activity_type,
        actor.entity_id AS actor_id,
        coalesce(actor.name, actor.entity_id) AS actor_name,
        post.post_id AS post_id,
        post.post_id AS target_post_id,
        NULL AS content,
        coalesce(liked.timestamp, '') AS timestamp
    }
    RETURN
      activity_id,
      activity_type,
      actor_id,
      actor_name,
      post_id,
      target_post_id,
      content,
      timestamp
    ORDER BY timestamp DESC, activity_id DESC
    """

    def __init__(self, driver: Driver, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database if database is not None else os.getenv("NEO4J_DATABASE")

    def list_session_social_dynamics(self, session_id: str) -> SessionSocialDynamicsData:
        """读取一个 Session 下的全部社交动态。"""

        params = {"session_id": session_id}
        with self._driver.session(database=self._database) as session:
            records = session.execute_read(
                lambda tx: list(tx.run(self._SESSION_SOCIAL_DYNAMICS_QUERY, params))
            )

        items: list[SessionSocialDynamicItem] = []
        for record in records:
            row = self._normalize_record(record)
            if row is None:
                continue
            items.append(
                SessionSocialDynamicItem(
                    activity_id=row["activity_id"],
                    activity_type=row["activity_type"],
                    actor_id=row["actor_id"],
                    actor_name=row["actor_name"],
                    post_id=row["post_id"],
                    target_post_id=row["target_post_id"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                )
            )

        return SessionSocialDynamicsData(
            session_id=session_id,
            total=len(items),
            items=items,
        )

    @staticmethod
    def _normalize_record(record: Any) -> dict[str, Any] | None:
        activity_id = record.get("activity_id")
        activity_type = record.get("activity_type")
        actor_id = record.get("actor_id")
        actor_name = record.get("actor_name")
        post_id = record.get("post_id")
        timestamp = record.get("timestamp")

        if not isinstance(activity_id, str) or not activity_id.strip():
            return None
        if activity_type not in {"post", "comment", "like"}:
            return None
        if not isinstance(actor_id, str) or not actor_id.strip():
            return None
        if not isinstance(post_id, str) or not post_id.strip():
            return None

        actor_name_text = actor_name if isinstance(actor_name, str) and actor_name else actor_id
        timestamp_text = timestamp if isinstance(timestamp, str) else ""
        target_post_id = record.get("target_post_id")
        content = record.get("content")

        return {
            "activity_id": activity_id,
            "activity_type": activity_type,
            "actor_id": actor_id,
            "actor_name": actor_name_text,
            "post_id": post_id,
            "target_post_id": target_post_id if isinstance(target_post_id, str) else None,
            "content": content if isinstance(content, str) else None,
            "timestamp": timestamp_text,
        }
