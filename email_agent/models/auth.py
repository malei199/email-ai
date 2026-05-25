"""
认证相关Pydantic模型
"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List


class LoginRequest(BaseModel):
    email: EmailStr


class LoginResponse(BaseModel):
    user_id: int
    name: Optional[str]
    email: str
    kg_matched: bool
    styles: List[str] = []
    token: str  # 简单token，实际可用JWT


class UserProfile(BaseModel):
    id: int
    email: str
    name: Optional[str]
    kg_matched: bool
    
    class Config:
        from_attributes = True
