from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.action_types import ActionType


class SocialAction(BaseModel):
    # 放在第一个字段：利用自回归特性，先让模型显式给出“思考”再给动作。
    inner_monologue: str = Field(
        ...,
        description=(
            "【必填，先输出】Agent 的内心独白与决策依据（第一人称）。"
            "请明确写出：1) 你观察到了什么（事件、对象、上下文）；"
            "2) 你的当前目标是什么；3) 为什么选择这个动作而不是其他动作；"
            "4) 预期结果与风险。"
            "要求：具体、可执行、不要空话，长度建议 30-120 字。"
        ),
    )
    action_type: ActionType = Field(
        ...,
        description=(
            "【必填】最终动作类型。"
            "可选值：post / like / comment / noop。"
            "必须与下面参数一致："
            "post 需要 content；"
            "like 需要 target_post_id；"
            "comment 需要 target_post_id + content；"
            "noop 不需要额外参数。"
        ),
    )
    content: Optional[str] = Field(
        None,
        description=(
            "帖子或评论正文。"
            "当 action_type=post 时必填；"
            "当 action_type=comment 时必填；"
            "其余动作应为空。"
            "建议包含清晰意图，避免无意义短句。"
        ),
    )
    target_post_id: Optional[str] = Field(
        None,
        description=(
            "目标帖子 ID。"
            "当 action_type=like/comment 时必填；"
            "当 action_type=post/noop 时应为空。"
            "必须是可解析的帖子标识，不能是自然语言描述。"
        ),
    )
