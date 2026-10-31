from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    Session,
    declarative_base,
    relationship,
    sessionmaker,
)


from backend.config import DATABASE_URL
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_timeout=10)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(32), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    title = Column(
        String(200),
        nullable=False,
        default="新对话",
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )


class CourtRoom(Base):
    __tablename__ = 'court_rooms'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    invite_code = Column(String(16), unique=True, nullable=False)
    creator_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    phase = Column(String(16), nullable=False, default='discussion')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CourtMember(Base):
    __tablename__ = 'court_members'
    __table_args__ = (UniqueConstraint('room_id', 'user_id'),)
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('court_rooms.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role = Column(String(16), nullable=False, default='pending')


class CourtMessage(Base):
    __tablename__ = 'court_messages'
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey('court_rooms.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    username = Column(String(32), nullable=False)
    role = Column(String(16), nullable=False)
    kind = Column(String(16), nullable=False, default='human')
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def init_db():
    from sqlalchemy import inspect
    if not {'users', 'conversations', 'messages', 'court_rooms', 'court_members', 'court_messages'}.issubset(inspect(engine).get_table_names()):
        raise RuntimeError('请先执行 python -m alembic upgrade head')
    print('PostgreSQL 已连接')


def get_db():
    database: Session = SessionLocal()

    try:
        yield database
    finally:
        database.close()
