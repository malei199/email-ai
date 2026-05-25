"""
历史会话路由
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from email_agent.database import get_db, Session as DBSession, Message
from email_agent.models.chat import SessionOut, MessageOut
from email_agent.services.auth_service import get_current_user

router = APIRouter(prefix="/api/sessions", tags=["历史会话"])


@router.get("", response_model=List[SessionOut])
def get_sessions(
    page: int = 1,
    size: int = 20,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    sessions = db.query(DBSession).filter(
        DBSession.user_id == user.id
    ).order_by(DBSession.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    
    return sessions


@router.get("/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(
    session_id: int,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    session = db.query(DBSession).filter(
        DBSession.id == session_id,
        DBSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = db.query(Message).filter(
        Message.session_id == session_id
    ).order_by(Message.created_at.asc()).all()
    
    return messages
