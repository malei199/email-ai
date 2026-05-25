"""
邮件智能助手 - FastAPI主入口
"""
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from email_agent.config import CORS_ORIGINS
from email_agent.database import init_db
from email_agent.routers import auth, morning_push, chat, styles, feedback, sessions

# 初始化数据库
init_db()

app = FastAPI(
    title="服装智能助手",
    description="基于双轨RAG + 知识图谱 + 微调模型的服装跟单智能助手",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API路由
app.include_router(auth.router)
app.include_router(morning_push.router)
app.include_router(chat.router)
app.include_router(styles.router)
app.include_router(feedback.router)
app.include_router(sessions.router)

# 静态文件（前端）
app.mount("/", StaticFiles(directory="email_agent/static", html=True), name="static")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("email_agent.main:app", host="0.0.0.0", port=8000, reload=True)
