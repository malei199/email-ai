"""
早推送路由
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from email_agent.database import get_db
from email_agent.models.morning_push import MorningPushResponse
from email_agent.services.auth_service import get_current_user
from email_agent.services.morning_push_service import generate_morning_push

router = APIRouter(prefix="/api/morning-push", tags=["早推送"])


@router.get("", response_model=MorningPushResponse)
def get_morning_push(
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    
    result = generate_morning_push(db, user)
    return result
