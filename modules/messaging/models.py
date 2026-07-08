from datetime import datetime
from enum import Enum

from sqlalchemy import (Column,Integer,String,Boolean,DateTime,ForeignKey,Enum as SqlEnum)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import UniqueConstraint, Text
import uuid

from core.database import Base


class MessageStatus(str, Enum):
    SENDING = "SENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"

class Chat(Base):
    __tablename__ = "chats"

    chat_id = Column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    userchats = relationship(
        "UserChat",
        back_populates="chat",
        cascade="all, delete-orphan",
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="Message.message_id",
    )

class UserChat(Base):
    __tablename__ = "user_chats"

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id"),
    )

    user_chat_id = Column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True),ForeignKey("users.user_id", ondelete="CASCADE"),nullable=False, index=True)

    chat_id = Column(UUID(as_uuid=True),ForeignKey("chats.chat_id", ondelete="CASCADE"),nullable=False, index=True)

    last_read_timestamp = Column(DateTime,default=datetime.utcnow,nullable=False)

    last_message_id = Column(Integer,ForeignKey("messages.message_id", ondelete="SET NULL"),nullable=True)

    unread_count = Column(Integer,default=0,nullable=False)

    # Relationships
    user = relationship("User", back_populates="user_chats")
    chat = relationship("Chat", back_populates="userchats")
    last_message = relationship("Message",foreign_keys=[last_message_id])


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(Integer, primary_key=True, autoincrement=True)

    chat_id = Column(UUID(as_uuid=True),ForeignKey("chats.chat_id", ondelete="CASCADE"),nullable=False,index=True)

    sender_id = Column(UUID(as_uuid=True),ForeignKey("users.user_id", ondelete="CASCADE"),nullable=False,index=True)

    text = Column(Text, nullable=False)

    is_edited = Column(Boolean, default=False, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    reply_to_message_id = Column(Integer,ForeignKey("messages.message_id", ondelete="SET NULL"),nullable=True)

    status = Column(SqlEnum(MessageStatus),default=MessageStatus.SENDING,nullable=False)

    created_at = Column(DateTime,default=datetime.utcnow,nullable=False)

    # Relationships
    sender = relationship("User", back_populates="messages")
    chat = relationship("Chat", back_populates="messages")
    reply_to_message = relationship("Message", remote_side=[message_id], foreign_keys=[reply_to_message_id], backref="replies", uselist=False,)