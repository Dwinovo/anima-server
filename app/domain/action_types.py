from __future__ import annotations

from enum import Enum


class ActionType(str, Enum):
    POST = "post"
    LIKE = "like"
    COMMENT = "comment"
    NOOP = "noop"
