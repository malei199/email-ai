"""
款号备注路由
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List

from email_agent.database import get_db, StyleNote
from email_agent.models.style import StyleOut, StyleNoteUpdate
from email_agent.services.auth_service import get_current_user
from email_agent.services.kg_adapter import query_styles_by_person

router = APIRouter(prefix="/api/styles", tags=["款号管理"])


@router.get("", response_model=List[StyleOut])
def get_styles(
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 从KG获取负责的款号
    kg_styles = []
    if user.name:
        result = query_styles_by_person(user.name)
        kg_styles = result.get("styles", [])
    
    # 获取用户备注
    notes = {
        note.style_id: note
        for note in db.query(StyleNote).filter(StyleNote.user_id == user.id).all()
    }
    
    # 合并数据
    styles = []
    for s in kg_styles:
        style_id = s["style_id"] if isinstance(s, dict) else s
        note = notes.get(style_id)
        styles.append(StyleOut(
            style_id=style_id,
            alias=note.alias if note else None,
            is_pinned=note.is_pinned if note else False,
            sort_order=note.sort_order if note else 0
        ))
    
    # 排序：置顶在前，然后按sort_order
    styles.sort(key=lambda x: (-x.is_pinned, x.sort_order, x.style_id))
    
    return styles


@router.put("/{style_id}")
def update_style(
    style_id: str,
    req: StyleNoteUpdate,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    note = db.query(StyleNote).filter(
        StyleNote.user_id == user.id,
        StyleNote.style_id == style_id
    ).first()
    
    if not note:
        note = StyleNote(user_id=user.id, style_id=style_id)
        db.add(note)
    
    if req.alias is not None:
        note.alias = req.alias
    if req.is_pinned is not None:
        note.is_pinned = req.is_pinned
    
    db.commit()
    db.refresh(note)
    
    return StyleOut(
        style_id=note.style_id,
        alias=note.alias,
        is_pinned=note.is_pinned,
        sort_order=note.sort_order
    )
