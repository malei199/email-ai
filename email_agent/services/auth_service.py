"""
认证服务
"""
import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from email_agent.database import User
from email_agent.services.kg_adapter import query_person_by_email, query_styles_by_person

# 简单token存储（生产环境应使用Redis + JWT）
_token_store: dict[str, int] = {}


def login(db: Session, email: str) -> dict:
    """
    用户登录：
    1. 查找或创建用户
    2. 查KG匹配身份
    3. 查负责的款号列表
    4. 生成token
    """
    # 查找或创建用户
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # 更新最后登录时间
    user.last_login = datetime.utcnow()
    
    # 查KG匹配身份
    person = query_person_by_email(email)
    styles = []
    
    if person:
        user.name = person.get("name")
        user.kg_matched = True
        
        # 查负责的款号
        style_data = query_styles_by_person(person["name"])
        styles = [s["style_id"] for s in style_data.get("styles", [])]
    
    db.commit()
    db.refresh(user)
    
    # 生成token
    token = str(uuid.uuid4())
    _token_store[token] = user.id
    
    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "kg_matched": user.kg_matched,
        "styles": styles,
        "token": token,
    }


def logout(token: str) -> bool:
    """退出登录"""
    if token in _token_store:
        del _token_store[token]
        return True
    return False


def get_user_id_by_token(token: str) -> int | None:
    """通过token获取用户ID"""
    return _token_store.get(token)


def get_current_user(db: Session, token: str) -> User | None:
    """获取当前登录用户"""
    user_id = get_user_id_by_token(token)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()
