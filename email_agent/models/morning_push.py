"""
早推送相关Pydantic模型
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class RiskItem(BaseModel):
    style_id: str
    alias: Optional[str]
    reason: str


class EventItem(BaseModel):
    style_id: str
    alias: Optional[str]
    event: str


class MorningPushSummary(BaseModel):
    total_styles: int
    risk_count: int
    event_count: int


class MorningPushResponse(BaseModel):
    date: date
    greeting: str
    summary: MorningPushSummary
    risks: List[RiskItem] = []
    events: List[EventItem] = []
    content: str  # Markdown完整内容
