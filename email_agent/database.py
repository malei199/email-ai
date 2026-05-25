"""
邮件智能助手 - 数据库ORM与初始化
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

from email_agent.config import DATABASE_URL

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String)
    kg_matched = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    # 关系
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    style_notes = relationship("StyleNote", back_populates="user", cascade="all, delete-orphan")
    morning_pushes = relationship("MorningPush", back_populates="user", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    """会话表"""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String)  # 显示标题
    style_id = Column(String)  # 关联款号（如有）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 分页续查状态
    omitted_data_id = Column(Integer, ForeignKey("omitted_data.id"), nullable=True)
    truncation_current_page = Column(Integer, default=0)
    truncation_page_size = Column(Integer, default=15)
    
    # 关系
    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at")
    omitted_data = relationship("OmittedData", back_populates="session", foreign_keys="[OmittedData.session_id]")


class Message(Base):
    """消息表"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    mode = Column(String, default="detailed")  # 'concise' | 'detailed'
    sources = Column(Text)  # JSON字符串
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    session = relationship("Session", back_populates="messages")
    feedback = relationship("Feedback", back_populates="message", uselist=False, cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint("mode IN ('concise', 'detailed')", name="check_mode"),
    )


class StyleNote(Base):
    """款号备注表"""
    __tablename__ = "style_notes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    style_id = Column(String, nullable=False)
    alias = Column(String)
    is_pinned = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="style_notes")
    
    __table_args__ = (UniqueConstraint("user_id", "style_id", name="uix_user_style"),)


class MorningPush(Base):
    """早推送记录表"""
    __tablename__ = "morning_pushes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    push_date = Column(Date, nullable=False)
    content = Column(Text, nullable=False)
    risk_count = Column(Integer, default=0)
    event_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="morning_pushes")
    
    __table_args__ = (UniqueConstraint("user_id", "push_date", name="uix_user_date"),)


class Feedback(Base):
    """反馈表"""
    __tablename__ = "feedback"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer)  # 1=👍, -1=👎
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    message = relationship("Message", back_populates="feedback")
    user = relationship("User", back_populates="feedbacks")
    
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="check_rating"),)


class OmittedData(Base):
    """被截断数据存储表"""
    __tablename__ = "omitted_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    
    # 对话信息（首次查询的上下文，不变）
    conversation = Column(Text)  # JSON：user_query, v2_thought, function_calls, timestamp
    
    # 当前剩余数据（每次截取后覆盖更新，逐渐减少）
    remaining_data = Column(Text)  # JSON：当前剩余的完整列表
    
    # 元信息
    original_count = Column(Integer)  # 首次查询的总数量
    query_type = Column(String)  # 查询类型，如 "kg_query.my_styles"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    session = relationship("Session", back_populates="omitted_data", foreign_keys="[OmittedData.session_id]")


def init_db():
    """初始化数据库（创建所有表）"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话（用于FastAPI依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
