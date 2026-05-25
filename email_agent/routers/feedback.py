"""
反馈路由
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from email_agent.database import get_db, Feedback
from email_agent.models.feedback import FeedbackCreate
from email_agent.services.auth_service import get_current_user

router = APIRouter(prefix="/api/feedback", tags=["反馈"])


@router.post("")
def create_feedback(
    req: FeedbackCreate,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 检查消息是否存在
    from email_agent.database import Message
    msg = db.query(Message).filter(Message.id == req.message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    
    # 检查是否已有反馈
    existing = db.query(Feedback).filter(Feedback.message_id == req.message_id).first()
    if existing:
        existing.rating = req.rating
        existing.comment = req.comment
        db.commit()
        return {"id": existing.id, "updated": True}
    
    feedback = Feedback(
        message_id=req.message_id,
        user_id=user.id,
        rating=req.rating,
        comment=req.comment
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    
    return {"id": feedback.id, "updated": False}
