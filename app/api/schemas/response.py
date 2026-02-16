from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None

    @staticmethod
    def success(
        data: Optional[T] = None,
        message: str = "success",
        code: int = 0,
    ) -> "APIResponse[T]":
        return APIResponse(code=code, message=message, data=data)

    @staticmethod
    def error(
        message: str = "error",
        code: int = 1,
        data: Optional[T] = None,
    ) -> "APIResponse[T]":
        return APIResponse(code=code, message=message, data=data)

