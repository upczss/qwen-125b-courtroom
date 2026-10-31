import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import (
    User,
    Conversation,
    Message,
    SessionLocal,
    get_db,
    init_db,
)
from backend.inference_client import model_service
from backend.generation_settings import GenerationSettings
from backend.generation_queue import queue
from backend.config import ALLOWED_ORIGINS
from backend.auth import router as auth_router, current_user, store
from backend.courts import router as court_router, shutdown as shutdown_courts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

SYSTEM_PROMPT = """
你是一个用于系统功能验证的中文法律问答助手。

要求：
1. 回答清晰、谨慎。
2. 信息不足时，明确说明需要补充的信息。
3. 不得虚构法律条文、司法解释或案例编号。
4. 区分一般性信息和针对具体案件的判断。
5. 回答仅供系统测试，不构成正式法律意见。
""".strip()


class ConversationCreate(BaseModel):
    title: str | None = Field(
        default=None,
        max_length=200,
    )


class MessageCreate(BaseModel):
    generation: GenerationSettings | None = None
    content: str = Field(
        min_length=1,
        max_length=20000,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("正在初始化数据库")
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(store.ping)

    await model_service.open()
    print(f"业务后端使用独立 {model_service.provider} 推理服务：{model_service.base_url}")

    yield

    await shutdown_courts()
    await model_service.close()
    print("服务已停止")


app = FastAPI(
    title="本地法律问答系统",
    version="0.2.0",
    lifespan=lifespan,
)


app.include_router(auth_router)
app.include_router(court_router)

@app.middleware('http')
async def origin_guard(request: Request, call_next):
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        from fastapi.responses import JSONResponse
        origin = request.headers.get('origin')
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse({'detail': '不允许跨站请求'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '不允许跨站请求'}, status_code=403)
        if request.method != 'DELETE' and request.headers.get('content-type','').split(';')[0] != 'application/json':
            return JSONResponse({'detail': '请使用 JSON 请求'}, status_code=415)
    return await call_next(request)


def conversation_to_dict(conversation: Conversation):
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def message_to_dict(message: Message):
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": await model_service.healthy(),
        "model": model_service.model_name,
        "inference_provider": model_service.provider,
        "quantization": model_service.quantization,
        "max_input_tokens": model_service.max_input_tokens,
        "max_new_tokens": model_service.max_new_tokens,
        "database": "PostgreSQL",
        "generation_slots": queue.limit,
        "queue_capacity": queue.max_waiting,
    }


@app.get("/api/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    return [
        conversation_to_dict(item)
        for item in conversations
    ]


@app.post("/api/conversations")
def create_conversation(
    request: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    title = (request.title or "").strip() or "新对话"

    conversation = Conversation(title=title, user_id=user.id)

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation_to_dict(conversation)


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="会话不存在",
        )

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .all()
    )

    return [
        message_to_dict(item)
        for item in messages
    ]


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="会话不存在",
        )

    if conversation_id in active_conversations:
        raise HTTPException(409, "会话正在生成，请等待结束后删除")
    db.delete(conversation)
    db.commit()

    return {
        "status": "deleted",
        "conversation_id": conversation_id,
    }


# This admission control is process-local: run one business worker for now.
active_conversations = queue.tickets


def prepare_turn(conversation_id, content, user_id):
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if conversation is None:
            raise HTTPException(404, "会话不存在")
        history = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": m.role, "content": m.content} for m in history)
        messages.append({"role": "user", "content": content})
        return messages


def save_user(conversation_id, content, user_id):
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if conversation is None:
            raise HTTPException(404, "会话不存在")
        message = Message(conversation_id=conversation_id, role="user", content=content)
        if conversation.title == "新对话":
            conversation.title = content[:30]
        conversation.updated_at = datetime.utcnow()
        db.add(message)
        db.commit()
        db.refresh(message)
        return message_to_dict(message), conversation_to_dict(conversation)


def save_answer(conversation_id, answer, user_id):
    with SessionLocal() as db:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if conversation is None:
            raise HTTPException(404, "生成过程中会话被删除")
        message = Message(conversation_id=conversation_id, role="assistant", content=answer)
        conversation.updated_at = datetime.utcnow()
        db.add(message)
        db.commit()
        db.refresh(message)
        return message_to_dict(message), conversation_to_dict(conversation)


def sse_event(data):
    return "data: " + json.dumps(data, ensure_ascii=False, default=str) + "\n\n"


def finish_metrics(metrics, started, called):
    metrics['end_to_end_seconds'] = round(perf_counter()-started, 4)
    first = metrics.get('model_ttft_seconds')
    metrics['request_ttft_seconds'] = round(first+called-started, 4) if first is not None else None
    print('推理请求完成：', metrics, flush=True)


async def begin_turn(conversation_id, request, user_id):
    content = request.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    messages = await asyncio.to_thread(prepare_turn, conversation_id, content, user_id)
    queue.reserve(conversation_id, user_id)
    try:
        messages = await model_service.prepare(messages, **({'settings': request.generation.api_parameters()} if request.generation else {}))
        user, conversation = await asyncio.to_thread(save_user, conversation_id, content, user_id)
        return messages, user, conversation
    except Exception as exc:
        queue.release(conversation_id)
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from exc
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "推理服务暂不可用，请稍后重试") from exc
    except BaseException:
        queue.release(conversation_id)
        raise


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, request: MessageCreate, user: User = Depends(current_user)):
    started = perf_counter()
    messages, saved_user, conversation = await begin_turn(conversation_id, request, user.id)
    try:
        queued_at = perf_counter()
        await queue.wait(conversation_id)
        metrics = {'queue_seconds': perf_counter()-queued_at}
        called = perf_counter()
        parts = []
        async for text in model_service.stream_chat(messages, metrics, **({'settings': request.generation.api_parameters()} if request.generation else {})):
            parts.append(text)
        answer, conversation = await asyncio.to_thread(save_answer, conversation_id, ''.join(parts).strip(), user.id)
        finish_metrics(metrics, started, called)
        return dict(user_message=saved_user, assistant_message=answer, conversation=conversation, metrics=metrics)
    except HTTPException:
        raise
    except Exception as exc:
        print('推理失败：', repr(exc), flush=True)
        raise HTTPException(502, "生成失败，请重试") from exc
    finally:
        queue.release(conversation_id)


@app.post("/api/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: int, request: MessageCreate, user: User = Depends(current_user)):
    started = perf_counter()
    messages, saved_user, conversation = await begin_turn(conversation_id, request, user.id)

    async def generate():
        try:
            yield sse_event(dict(type='start', user_message=saved_user, conversation=conversation))
            queued_at = perf_counter()
            event = queue.tickets[conversation_id]
            while not event.is_set():
                yield sse_event(dict(type='queued', position=queue.position(conversation_id), message='正在等待生成名额'))
                remaining = 120-(perf_counter()-queued_at)
                if remaining <= 0:
                    raise HTTPException(504, '排队超过120秒，请重试')
                try:
                    await asyncio.wait_for(event.wait(), timeout=min(5,remaining))
                except asyncio.TimeoutError:
                    pass
            yield sse_event(dict(type='generating'))
            metrics = {'queue_seconds': perf_counter()-queued_at}
            called = perf_counter()
            parts = []
            async for text in model_service.stream_chat(messages, metrics, **({'settings': request.generation.api_parameters()} if request.generation else {})):
                reasoning = metrics.pop('_reasoning_delta', None)
                if reasoning:
                    yield sse_event(dict(type='reasoning', content=reasoning))
                if not text:
                    continue
                parts.append(text)
                yield sse_event(dict(type='delta', content=text))
            answer, current = await asyncio.to_thread(save_answer, conversation_id, ''.join(parts).strip(), user.id)
            finish_metrics(metrics, started, called)
            yield sse_event(dict(type='done', assistant_message=answer, conversation=current, metrics=metrics))
        except Exception as exc:
            print('流式推理失败：', repr(exc), flush=True)
            yield sse_event(dict(type='error', message=exc.detail if isinstance(exc, HTTPException) else '生成失败，请重试'))
        finally:
            queue.release(conversation_id)

    from starlette.background import BackgroundTask
    return StreamingResponse(generate(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        background=BackgroundTask(queue.cleanup, conversation_id, queue.tickets[conversation_id]))


# 必须放在所有 /api 路由之后
app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIR,
        html=True,
    ),
    name="frontend",
)
