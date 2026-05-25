"""
反馈相关Pydantic模型
"""
from pydantic import BaseModel
from typing import Optional, Literal


class FeedbackCreate(BaseModel):
    message_id: int
    rating: Literal[-1, 1]
    comment: Optional[str] = None
