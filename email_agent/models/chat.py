"""
对话相关Pydantic模型
"""
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime


class ChatRequest(BaseModel):
    session_id: Optional[int] = None
    message: str
    mode: Literal["concise", "detailed"] = "detailed"


class SourceItem(BaseModel):
    type: str  # 'kg', 'rag', 'term', 'model'
    query: Optional[str] = None
    style_id: Optional[str] = None
    collection: Optional[str] = None
    count: Optional[int] = None


class ChatDoneData(BaseModel):
    message_id: int
    content: str
    sources: List[SourceItem] = []
    mode: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    mode: str
    sources: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: int
    title: Optional[str]
    style_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
