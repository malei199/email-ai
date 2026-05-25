"""
款号备注相关Pydantic模型
"""
from pydantic import BaseModel
from typing import Optional


class StyleNoteUpdate(BaseModel):
    alias: Optional[str] = None
    is_pinned: Optional[bool] = None


class StyleOut(BaseModel):
    style_id: str
    alias: Optional[str]
    is_pinned: bool
    sort_order: int
    
    class Config:
        from_attributes = True
