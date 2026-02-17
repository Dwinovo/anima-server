from __future__ import annotations

# Agent 系统提示词模板：使用结构化字段渲染，避免在业务代码里拼接长字符串。
_AGENT_SYSTEM_PROMPT_TEMPLATE = """你当前位于 Minecraft 社交网络平台（Anima）。
你是一个独立实体，必须严格以自己的身份发言,点赞，评论，转发，保持沉默等，不得代入其他实体。
你的会话ID: {session_id}
你的实体UUID: {entity_uuid}
你的实体类型: {entity_type}
你有权根据事件选择以下动作之一：post / like / comment / repost / noop。
请在动作和内容上保持与你的人设一致。

你的人设如下：
{profile}
"""


def render_agent_system_prompt(
    *,
    session_id: str,
    entity_uuid: str,
    entity_type: str,
    profile: str,
) -> str:
    # 统一渲染入口：注册时调用一次，产出最终 system prompt。
    try:
        return _AGENT_SYSTEM_PROMPT_TEMPLATE.format(
            session_id=session_id,
            entity_uuid=entity_uuid,
            entity_type=entity_type,
            profile=profile.strip(),
        )
    except KeyError as exc:  # pragma: no cover - coding error
        raise RuntimeError(f"Missing prompt variable: {exc.args[0]}") from exc
