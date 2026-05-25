"""
认证路由
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from email_agent.database import get_db
from email_agent.models.auth import LoginRequest, LoginResponse
from email_agent.services.auth_service import login as do_login, logout as do_logout, get_current_user

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse)
def login_endpoint(req: LoginRequest, db: Session = Depends(get_db)):
    result = do_login(db, req.email)
    return result


@router.post("/logout")
def logout_endpoint(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    success = do_logout(token)
    return {"success": success}


@router.get("/me")
def me_endpoint(authorization: str = Header(...), db: Session = Depends(get_db)):
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或token已过期")
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "kg_matched": user.kg_matched,
    }
