from __future__ import annotations

import json
import os
from typing import Any

from neo4j import Driver


class PerceptionService:
    """为单个 Agent 生成个性化的近期感知（Markdown 文本）。"""

    _PERCEPTION_QUERY = """
    MATCH (me:Entity {session_id: $session_id, entity_id: $agent_uuid})

    CALL (me) {
      CALL (me) {
        MATCH (me)-[:INITIATED]->(evt:Event {session_id: $session_id})
        OPTIONAL MATCH (evt)-[:TARGETED]->(obj:Entity {session_id: $session_id})
        RETURN {
          timestamp: evt.timestamp,
          world_time: evt.world_time,
          verb: evt.verb,
          role: 'subject',
          counterpart_id: obj.entity_id,
          counterpart_name: coalesce(obj.name, obj.entity_id),
          details: evt.details
        } AS row
        UNION ALL
        MATCH (me)<-[:TARGETED]-(evt:Event {session_id: $session_id})
        OPTIONAL MATCH (sub:Entity {session_id: $session_id})-[:INITIATED]->(evt)
        RETURN {
          timestamp: evt.timestamp,
          world_time: evt.world_time,
          verb: evt.verb,
          role: 'object',
          counterpart_id: sub.entity_id,
          counterpart_name: coalesce(sub.name, sub.entity_id),
          details: evt.details
        } AS row
      }
      WITH row
      ORDER BY row.timestamp DESC
      RETURN collect(row)[0..5] AS physical_events
    }

    CALL (me) {
      CALL (me) {
        MATCH (me)-[:POSTED]->(my_post:SocialPost {session_id: $session_id})
        MATCH (actor:Entity {session_id: $session_id})-[liked:LIKED]->(my_post)
        WHERE actor.entity_id <> me.entity_id
        RETURN {
          timestamp: liked.timestamp,
          actor_id: actor.entity_id,
          actor_name: coalesce(actor.name, actor.entity_id),
          action_type: 'LIKE',
          post_id: my_post.post_id,
          content: ''
        } AS row
        UNION ALL
        MATCH (me)-[:POSTED]->(my_post:SocialPost {session_id: $session_id})
        MATCH (comment:SocialPost {session_id: $session_id, type: 'COMMENT'})-[:REPLIED_TO]->(my_post)
        MATCH (actor:Entity {session_id: $session_id})-[:POSTED]->(comment)
        WHERE actor.entity_id <> me.entity_id
        RETURN {
          timestamp: comment.timestamp,
          actor_id: actor.entity_id,
          actor_name: coalesce(actor.name, actor.entity_id),
          action_type: 'COMMENT',
          post_id: my_post.post_id,
          content: comment.content,
          comment_id: comment.post_id
        } AS row
      }
      WITH row
      ORDER BY row.timestamp DESC
      RETURN collect(row) AS social_notifications
    }

    CALL (me) {
      MATCH (post:SocialPost {session_id: $session_id, type: 'ORIGINAL'})
      OPTIONAL MATCH (author:Entity {session_id: $session_id})-[:POSTED]->(post)
      WITH post, author
      ORDER BY post.timestamp DESC
      LIMIT 5
      CALL (post) {
        OPTIONAL MATCH path=(comment:SocialPost {session_id: $session_id, type: 'COMMENT'})-[:REPLIED_TO*1..]->(post)
        OPTIONAL MATCH (comment_author:Entity {session_id: $session_id})-[:POSTED]->(comment)
        WITH path, comment, comment_author
        WHERE comment IS NOT NULL
        RETURN collect(DISTINCT {
          comment_id: comment.post_id,
          parent_id: nodes(path)[1].post_id,
          depth: length(path),
          timestamp: comment.timestamp,
          content: comment.content,
          author_id: comment_author.entity_id,
          author_name: coalesce(comment_author.name, comment_author.entity_id)
        }) AS comments
      }
      RETURN collect({
        post_id: post.post_id,
        timestamp: post.timestamp,
        content: post.content,
        author_id: author.entity_id,
        author_name: coalesce(author.name, author.entity_id),
        comments: comments
      }) AS timeline_posts
    }

    RETURN physical_events, social_notifications, timeline_posts
    """

    def __init__(self, driver: Driver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database if database is not None else os.getenv("NEO4J_DATABASE")

    def get_formatted_perception(self, session_id: str, agent_uuid: str) -> str:
        """读取并格式化单个 Agent 的三维感知视图。"""

        payload = self._load_perception_payload(session_id=session_id, agent_uuid=agent_uuid)
        return self._format_markdown(agent_uuid=agent_uuid, payload=payload)

    def _load_perception_payload(self, *, session_id: str, agent_uuid: str) -> dict[str, list[dict[str, Any]]]:
        params = {
            "session_id": session_id,
            "agent_uuid": agent_uuid,
        }
        with self._driver.session(database=self._database) as session:
            record = session.execute_read(
                lambda tx: tx.run(self._PERCEPTION_QUERY, params).single()
            )

        if record is None:
            return {
                "physical_events": [],
                "social_notifications": [],
                "timeline_posts": [],
            }

        physical_events = record.get("physical_events") or []
        social_notifications = record.get("social_notifications") or []
        timeline_posts = record.get("timeline_posts") or []
        return {
            "physical_events": [dict(item) for item in physical_events],
            "social_notifications": [dict(item) for item in social_notifications],
            "timeline_posts": [dict(item) for item in timeline_posts],
        }

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("\n", " ").strip()

    @staticmethod
    def _pretty_details(value: Any) -> str:
        if value is None:
            return "{}"
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value
            return json.dumps(parsed, ensure_ascii=False)
        return str(value)

    def _format_markdown(self, *, agent_uuid: str, payload: dict[str, list[dict[str, Any]]]) -> str:
        physical_events = payload["physical_events"]
        social_notifications = payload["social_notifications"]
        timeline_posts = payload["timeline_posts"]

        lines: list[str] = [
            f"# Agent {agent_uuid} 感知快照",
            "",
            "## 1. 物理体感（最近 5 条）",
        ]
        if not physical_events:
            lines.append("- 附近风平浪静，暂无与你直接相关的物理事件。")
        else:
            for item in physical_events:
                verb = self._safe_text(item.get("verb")) or "UNKNOWN"
                timestamp = self._safe_text(item.get("timestamp")) or "unknown_time"
                world_time = self._safe_text(item.get("world_time")) or "unknown_world_time"
                counterpart = self._safe_text(item.get("counterpart_name")) or "未知实体"
                details = self._pretty_details(item.get("details"))
                role = self._safe_text(item.get("role"))
                if role == "subject":
                    action_desc = f"你对 {counterpart} 发起了 `{verb}`"
                else:
                    action_desc = f"{counterpart} 对你发起了 `{verb}`"
                lines.append(
                    f"- [{timestamp}] (world_time={world_time}) {action_desc} | details={details}"
                )

        lines.extend(
            [
                "",
                "## 2. 社交提醒",
            ]
        )
        if not social_notifications:
            lines.append("- 世界很安静，没有任何人关注你。")
        else:
            for item in social_notifications:
                timestamp = self._safe_text(item.get("timestamp")) or "unknown_time"
                actor = self._safe_text(item.get("actor_name")) or "未知玩家"
                action_type = self._safe_text(item.get("action_type")) or "UNKNOWN"
                post_id = self._safe_text(item.get("post_id")) or "unknown_post"
                if action_type == "LIKE":
                    lines.append(
                        f"- [{timestamp}] @{actor} 点赞了你的帖子 `post_id={post_id}`"
                    )
                else:
                    content = self._safe_text(item.get("content"))
                    comment_id = self._safe_text(item.get("comment_id")) or "unknown_comment"
                    lines.append(
                        f"- [{timestamp}] @{actor} 评论了你的帖子 `post_id={post_id}`: "
                        f"{content} (`comment_id={comment_id}`)"
                    )

        lines.extend(
            [
                "",
                "## 3. 朋友圈时间线（最新 5 条主帖）",
            ]
        )
        if not timeline_posts:
            lines.append("- 暂无主帖动态。")
        else:
            for post in timeline_posts:
                post_id = self._safe_text(post.get("post_id")) or "unknown_post"
                author = self._safe_text(post.get("author_name")) or "未知玩家"
                timestamp = self._safe_text(post.get("timestamp")) or "unknown_time"
                content = self._safe_text(post.get("content"))
                lines.append(f"- 主帖 `post_id={post_id}` | @{author} | {timestamp}")
                lines.append(f"  内容: {content}")
                lines.extend(
                    self._format_comment_tree(
                        root_post_id=post_id,
                        comments=post.get("comments") or [],
                    )
                )

        return "\n".join(lines)

    def _format_comment_tree(self, *, root_post_id: str, comments: list[dict[str, Any]]) -> list[str]:
        if not comments:
            return ["  └─ 暂无评论"]

        by_parent: dict[str, list[dict[str, Any]]] = {}
        for raw in comments:
            item = dict(raw)
            parent_id = self._safe_text(item.get("parent_id")) or root_post_id
            by_parent.setdefault(parent_id, []).append(item)

        for items in by_parent.values():
            items.sort(key=lambda entry: self._safe_text(entry.get("timestamp")))

        lines: list[str] = []

        def walk(parent_id: str, prefix: str) -> None:
            children = by_parent.get(parent_id, [])
            for idx, child in enumerate(children):
                is_last = idx == len(children) - 1
                connector = "└─" if is_last else "├─"
                comment_id = self._safe_text(child.get("comment_id")) or "unknown_comment"
                author = self._safe_text(child.get("author_name")) or "未知玩家"
                content = self._safe_text(child.get("content"))
                lines.append(
                    f"{prefix}{connector} 评论 `comment_id={comment_id}` @{author}: {content}"
                )
                child_prefix = f"{prefix}{'   ' if is_last else '│  '}"
                walk(comment_id, child_prefix)

        walk(root_post_id, "  ")
        if not lines:
            return ["  └─ 暂无评论"]
        return lines
