"""
SSE 流式对话路由（Mock 模式）

流程：
  1. 创建 session
  2. 保存用户消息
  3. 调用 chat_agent.process_message() 获取流式事件
  4. 收集 assistant 最终回答
  5. 保存完整 mock session_flow（user + v3 + v2×N + tool×N + assistant）
  6. 返回 SSE 流
"""

import json
import traceback
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from email_agent.database import get_db, Message, Session as ChatSession, OmittedData
from email_agent.agents.chat_agent import process_message
from email_agent.services.auth_service import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: str = "detailed"
    
    class Config:
        # 允许通过属性方式访问，兼容旧代码
        pass


# ---------------------------------------------------------------------------
# SSE 生成器
# ---------------------------------------------------------------------------

async def sse_stream(
    db: Session,
    user_id: str,
    req: ChatRequest
) -> AsyncGenerator[str, None]:
    """
    SSE 流式生成器
    
    只输出 delta + done 事件，不展示 thinking 过程。
    内部消化 v3/v2/tool 步骤，只向用户展示最终回答。
    但完整 session_flow 会保存到数据库。
    """
    session_id = req.session_id
    user_message = req.message.strip()
    mode = req.mode
    
    # ---- 创建或复用 session ----
    if session_id:
        chat_session = db.query(ChatSession).filter(
            ChatSession.id == session_id
        ).first()
        if not chat_session:
            chat_session = ChatSession(id=session_id, user_id=user_id)
            db.add(chat_session)
            db.commit()
    else:
        # 新会话：用用户第一个问题作为标题（截取前20字）
        title = user_message[:20] if len(user_message) <= 20 else user_message[:20] + "..."
        chat_session = ChatSession(user_id=user_id, title=title)
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
        session_id = chat_session.id
    
    # ---- 保存用户消息 ----
    user_msg = Message(
        session_id=session_id,
        role="user",
        content=user_message,
    )
    db.add(user_msg)
    db.commit()
    
    # ---- 检测续查请求 ----
    # 如果用户说"继续"等，直接走续查流程，不调用 process_message
    from email_agent.agents.intent_router import is_continuation
    
    if is_continuation(user_message):
        # 续查流程
        async for event in _handle_continuation_stream(db, chat_session, user_message):
            yield event
        return
    
    # ---- 流式输出 ----
    session_flow = []  # 收集真实 session_flow
    truncation_info = None  # 截断信息（用于续查）
    
    try:
        async for event in process_message(user_message, mode=mode):
            event_type = event.get("event")
            event_data = event.get("data", {})
            
            if event_type == "delta":
                content = event_data.get("content", "")
                yield f"event: delta\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            
            elif event_type == "thought":
                thought = event_data.get("thought", "")
                yield f"event: thought\ndata: {json.dumps({'thought': thought}, ensure_ascii=False)}\n\n"
            
            elif event_type == "done":
                # 提取真实 session_flow
                session_flow = event_data.get("session_flow", [])
                truncation_info = event_data.get("truncation_info")
                # done 事件只输出必要字段，避免数据过大导致前端解析问题
                done_payload = {
                    "content": event_data.get("content", ""),
                    "sources": event_data.get("sources", []),
                    "mode": event_data.get("mode", "detailed"),
                }
                yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
    
    except Exception as e:
        error_msg = f"处理消息时出错: {str(e)}"
        traceback.print_exc()
        yield f"event: error\ndata: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        return
    
    # ---- 保存真实 session_flow 到数据库 ----
    # session_flow 包含: user → v3 → [v2 → tool → ...] → [v1] → assistant
    # 其中 user 已经保存过了，跳过；其余全部保存
    for step in session_flow:
        if step.get("role") == "user":
            continue  # 已保存
        
        db.add(Message(
            session_id=session_id,
            role=step["role"],
            content=step["content"],
        ))
    
    # ---- 保存截断信息到 OmittedData（用于续查）----
    if truncation_info:
        _save_truncation_info(db, chat_session, truncation_info)
    
    db.commit()


# ---------------------------------------------------------------------------
# FastAPI 端点
# ---------------------------------------------------------------------------

@router.post("", include_in_schema=True)
async def chat_endpoint(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    """
    对话端点，返回 SSE 流式响应
    
    SSE 事件：
      - delta: 最终回答内容
      - done: 完成标记，包含完整内容
      - error: 错误信息
    """
    authorization = request.headers.get("Authorization", "")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = user.id
    
    return StreamingResponse(
        sse_stream(db, user_id, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---------------------------------------------------------------------------
# 续查流式处理
# ---------------------------------------------------------------------------

async def _handle_continuation_stream(
    db: Session,
    chat_session: ChatSession,
    user_message: str,
) -> AsyncGenerator[str, None]:
    """
    处理续查请求的 SSE 流
    
    流程：
    1. 查找 session 的 OmittedData
    2. 读取 remaining_data
    3. 使用 ResultTruncator 截取下一页
    4. 生成回答并流式输出
    5. 更新 remaining_data（覆盖）
    """
    import json
    from email_agent.services.result_truncator import ResultTruncator
    
    session_id = chat_session.id
    
    # 查找 OmittedData
    omitted = db.query(OmittedData).filter(
        OmittedData.session_id == session_id
    ).order_by(OmittedData.created_at.desc()).first()
    
    if not omitted:
        content = "该会话没有可续查的数据，请发起新的查询。"
        yield f"event: delta\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        
        # 保存消息
        db.add(Message(session_id=session_id, role="user", content=user_message))
        db.add(Message(session_id=session_id, role="assistant", content=content))
        db.commit()
        return
    
    # 读取剩余数据
    remaining_data = json.loads(omitted.remaining_data or "[]")
    if not remaining_data:
        content = "已显示全部内容，没有更多数据。"
        yield f"event: delta\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        
        # 保存消息
        db.add(Message(session_id=session_id, role="user", content=user_message))
        db.add(Message(session_id=session_id, role="assistant", content=content))
        db.commit()
        return
    
    # 读取对话上下文
    conversation = json.loads(omitted.conversation or "{}")
    query_type = omitted.query_type or "kg_query.my_styles"
    
    # 构造 raw_result
    primary_field = _get_primary_field(query_type)
    raw_result = {primary_field: remaining_data, "total": len(remaining_data)}
    
    # 截取下一页
    truncator = ResultTruncator()
    page_size = chat_session.truncation_page_size or 15
    
    result = truncator.truncate(
        raw_result=raw_result,
        query_type=query_type,
        max_items=page_size,
        conversation={
            **conversation,
            "user_query": user_message,
            "continuation": True,
            "page": chat_session.truncation_current_page + 1,
        },
    )
    
    # 生成回答
    answer = _build_continuation_answer(result, chat_session.truncation_current_page + 1)
    
    # 流式输出
    yield f"event: delta\ndata: {json.dumps({'content': answer}, ensure_ascii=False)}\n\n"
    
    # 构建 session_flow
    session_flow = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": answer},
    ]
    
    yield f"event: done\ndata: {json.dumps({'content': answer, 'session_flow': session_flow}, ensure_ascii=False)}\n\n"
    
    # 更新 OmittedData（覆盖 remaining_data）
    omitted.remaining_data = json.dumps(result.omitted_data or [], ensure_ascii=False)
    omitted.updated_at = datetime.utcnow()
    db.add(omitted)
    
    # 更新 session
    chat_session.truncation_current_page = chat_session.truncation_current_page + 1
    db.add(chat_session)
    
    # 保存消息
    db.add(Message(session_id=session_id, role="user", content=user_message))
    db.add(Message(session_id=session_id, role="assistant", content=answer))
    db.commit()


# ---------------------------------------------------------------------------
# 保存截断信息
# ---------------------------------------------------------------------------

def _save_truncation_info(db: Session, chat_session: ChatSession, truncation_info: dict):
    """
    保存截断信息到 OmittedData 表，并更新 session 的续查状态
    
    设计原则：
    - 每个查询创建一个 OmittedData 记录
    - remaining_data 会被后续续查覆盖更新
    - session.omitted_data_id 始终指向最新的 OmittedData
    """
    import json
    from datetime import datetime
    
    conversation = truncation_info.get("conversation", {})
    remaining_data = truncation_info.get("remaining_data", {})
    
    # 查找是否已有该 session 的 OmittedData
    existing = db.query(OmittedData).filter(
        OmittedData.session_id == chat_session.id
    ).order_by(OmittedData.created_at.desc()).first()
    
    if existing:
        # 更新现有记录（覆盖 remaining_data）
        existing.remaining_data = json.dumps(remaining_data, ensure_ascii=False)
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        omitted_data_id = existing.id
    else:
        # 创建新记录
        omitted = OmittedData(
            session_id=chat_session.id,
            conversation=json.dumps(conversation, ensure_ascii=False),
            remaining_data=json.dumps(remaining_data, ensure_ascii=False),
            original_count=truncation_info.get("original_count", 0),
            query_type=truncation_info.get("query_type", ""),
        )
        db.add(omitted)
        db.flush()  # 获取 ID
        omitted_data_id = omitted.id
    
    # 更新 session 状态
    chat_session.omitted_data_id = omitted_data_id
    chat_session.truncation_current_page = chat_session.truncation_current_page + 1
    db.add(chat_session)


# ---------------------------------------------------------------------------
# 续查端点
# ---------------------------------------------------------------------------

@router.post("/continue")
async def continue_chat(
    req: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    续查端点：用户说"继续"或"剩下的"时，直接返回剩余的所有数据
    
    流程：
    1. 查找 session 的 OmittedData
    2. 读取 remaining_data（完整的 raw_result 结构）
    3. 直接生成回答（不过模型，不截取）
    4. 删除 OmittedData
    5. 更新 session 和消息
    """
    import json
    from email_agent.agents.v2_orchestrator import continue_v2_query
    
    authorization = request.headers.get("Authorization", "")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = user.id
    session_id = req.session_id
    
    if not session_id:
        return {"error": "续查需要提供 session_id"}
    
    # 查找 session
    chat_session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not chat_session:
        return {"error": "会话不存在"}
    
    # 查找 OmittedData
    omitted = db.query(OmittedData).filter(
        OmittedData.session_id == session_id
    ).order_by(OmittedData.created_at.desc()).first()
    
    if not omitted:
        return {"content": "已显示全部内容，没有更多数据。"}
    
    # 读取剩余数据（完整的 raw_result 结构）
    remaining_data = json.loads(omitted.remaining_data or "{}")
    if not remaining_data:
        return {"content": "已显示全部内容，没有更多数据。"}
    
    query_type = omitted.query_type or "kg_query.my_styles"
    
    # 直接生成回答（不过模型，不截取）
    answer = await continue_v2_query(remaining_data, query_type)
    
    # 删除 OmittedData（已用完）
    db.delete(omitted)
    
    # 更新 session
    chat_session.omitted_data_id = None
    chat_session.truncation_current_page = 0
    db.add(chat_session)
    
    # 保存消息
    db.add(Message(session_id=session_id, role="user", content=req.message))
    db.add(Message(session_id=session_id, role="assistant", content=answer))
    db.commit()
    
    return {"content": answer}


def _get_primary_field(query_type: str) -> str:
    """从 query_type 推断主字段名"""
    # kg_query.my_styles -> styles
    # kg_query.style_summaries -> summaries
    # rag_query.semantic_search -> events
    if "style_summaries" in query_type:
        return "summaries"
    elif "semantic_search" in query_type or "timeline" in query_type:
        return "events"
    elif "collaborators" in query_type:
        return "collaborators"
    elif "factory_delays" in query_type:
        return "factories"
    elif "term_translation" in query_type:
        return "translations"
    else:
        return "styles"


def _build_continuation_answer(result, page: int) -> str:
    """构建续查回答"""
    returned = result.returned_count
    remaining = len(result.omitted_data or [])
    total = result.original_count
    note = result.truncation_note
    
    lines = [
        f"**第 {page} 页**（共 {total} 条）",
        "",
        f"本次显示 {returned} 条，剩余 {remaining} 条。",
    ]
    
    if note:
        lines.append(f"*{note}*")
    
    if remaining > 0:
        lines.append("")
        lines.append("如需继续查看，请说\"继续\"。")
    else:
        lines.append("")
        lines.append("✅ 已显示全部内容。")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 获取对话历史
# ---------------------------------------------------------------------------

@router.get("/history/{session_id}")
async def get_history(session_id: str, db: Session = Depends(get_db)):
    """
    获取对话历史（包含完整 mock session_flow）
    
    Returns:
        {
            "session_id": "...",
            "messages": [
                {"role": "user", "content": "...", "created_at": "..."},
                {"role": "v3", "content": "...", "created_at": "..."},
                {"role": "v2", "content": "...", "created_at": "..."},
                {"role": "tool", "content": "...", "created_at": "..."},
                {"role": "assistant", "content": "...", "created_at": "..."}
            ]
        }
    """
    messages = db.query(Message).filter(
        Message.session_id == session_id
    ).order_by(Message.created_at.asc()).all()
    
    return {
        "session_id": session_id,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ]
    }
