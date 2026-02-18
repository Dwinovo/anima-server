from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field


class MinecraftLocation(BaseModel):
    dimension: str = Field(
        ...,
        description="事件发生的维度，例如: 'minecraft:overworld', 'minecraft:the_nether'",
    )
    biome: str = Field(
        ...,
        description="事件发生时的生物群系，例如: 'minecraft:plains', 'minecraft:desert'。用于提供环境感知上下文",
    )
    coordinates: Tuple[float, float, float] = Field(
        ...,
        description="(x, y, z) 绝对坐标。精确到浮点数用于分析 Agent 的微观移动轨迹与空间距离",
    )


class MinecraftEntity(BaseModel):
    entity_id: str = Field(
        ...,
        description="实体的全局唯一标识。玩家填 UUID，生物填 Entity UUID，固定方块可填坐标哈希 'x_y_z'",
    )
    entity_type: str = Field(
        ...,
        description="游戏内注册名，例如: 'minecraft:player', 'minecraft:villager', 'minecraft:chest'",
    )
    name: Optional[str] = Field(
        None,
        description="玩家昵称或自定义命名牌，方便人类查阅和日志溯源",
    )
    location: Optional[MinecraftLocation] = Field(
        None,
        description="该实体在当前事件发生时的物理位置",
    )
    state: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "实体的瞬时状态集合（如: 血量、饱食度、手持物品、特定槽位内容）。"
            "这是 Agent 做出下一步决策的核心依据。"
        ),
    )


class MinecraftAction(BaseModel):
    verb: str = Field(
        ...,
        description=(
            "核心拓扑关系词（图谱中的 Edge Label）。"
            "例如: 'ATTACKED', 'CHATTED_WITH', 'DROPPED_ITEM', 'BROKE_BLOCK'"
        ),
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "动作的具体参数（图谱中 Edge 的 Properties）。"
            "例如 CHATTED_WITH 包含 {'message': '...', 'channel': 'global'}；"
            "ATTACKED 包含 {'damage': 5.0, 'weapon': 'minecraft:iron_sword'}。"
        ),
    )


class EventRequest(BaseModel):
    session_id: str = Field(
        ...,
        description="数据隔离沙盒 ID。用于区分不同的服务器实例或推演批次，防止图谱数据污染",
    )
    world_time: int = Field(
        ...,
        description="游戏内的绝对 Tick 时间 (0-24000)。用于构建时间序列，分析昼夜行为模式",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="现实世界的系统时间戳",
    )
    subject: MinecraftEntity = Field(
        ...,
        description="【主】动作发起者。通常是 Agent 驱动的 Player",
    )
    action: MinecraftAction = Field(
        ...,
        description="【谓】动作类型及细节",
    )
    object: Optional[MinecraftEntity] = Field(
        None,
        description=(
            "【宾】动作承受者。可以是另一个 Player、生物或方块。"
            "如果是全局广播聊天或纯移动操作，此项为 None"
        ),
    )


class EventResponse(BaseModel):
    session_id: str
