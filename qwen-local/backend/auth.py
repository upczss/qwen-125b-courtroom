import hashlib
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
import redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import REDIS_URL, COOKIE_SECURE
from backend.database import User, get_db, SessionLocal

router = APIRouter(prefix='/api/auth')
store = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = 'qwen_session'
TTL = 86400


def session_key(token):
    return 'qwen:session:' + hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, '请先登录')
    try:
        uid = store.get(session_key(token))
    except redis.RedisError as exc:
        raise HTTPException(503, '登录服务暂不可用') from exc
    with SessionLocal() as db:
        user = db.get(User, int(uid)) if uid else None
        if user is None or not user.is_active:
            raise HTTPException(401, '登录已过期，请重新登录')
        db.expunge(user)
        return user


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


def public(user):
    return {'id': user.id, 'username': user.username}


def limit(request):
    key = 'qwen:auth-rate:' + (request.client.host if request.client else 'unknown')
    try:
        # Atomic increment + expiry; do not trust forwarded IP headers here.
        count = store.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],300) end; return n", 1, key)
    except redis.RedisError as exc:
        raise HTTPException(503, '登录服务暂不可用') from exc
    if count > 30:
        raise HTTPException(429, '操作过于频繁，请五分钟后再试')


def establish(user, response):
    token = secrets.token_urlsafe(32)
    try:
        store.setex(session_key(token), TTL, user.id)
    except redis.RedisError as exc:
        raise HTTPException(503, '登录服务暂不可用，请稍后登录') from exc
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True,
                        secure=COOKIE_SECURE, samesite='strict', path='/')


@router.post('/register', status_code=201)
def register(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request)
    username = body.username.strip().lower()
    if not re.fullmatch(r'[a-z0-9_]{3,32}', username):
        raise HTTPException(400, '用户名需为3–32位英文字母、数字或下划线')
    user = User(username=username, password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '用户名已存在')
    db.refresh(user)
    establish(user, response)
    return public(user)


@router.post('/login')
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request)
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or user is None or not user.is_active:
        raise HTTPException(401, '用户名或密码错误')
    old = request.cookies.get(COOKIE)
    if old:
        store.delete(session_key(old))
    establish(user, response)
    return public(user)


@router.get('/me')
def me(user: User = Depends(current_user)):
    return public(user)


@router.post('/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        try:
            store.delete(session_key(token))
        except redis.RedisError as exc:
            raise HTTPException(503, '退出失败，请重试') from exc
    response.delete_cookie(COOKIE, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict')
    return {'status': 'logged_out'}
