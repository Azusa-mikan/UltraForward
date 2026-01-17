from sqlalchemy import UniqueConstraint, Integer, BigInteger, String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from uf.src.sql import Base

class Verify(Base):
    __tablename__ = "verify_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    userid: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, comment="Telegram 用户ID")
    code: Mapped[str] = mapped_column(String(5), nullable=False, comment="验证码")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, comment="过期时间")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否验证")

class Block(Base):
    __tablename__ = "block_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    userid: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, comment="Telegram 用户ID")
    pinned_msg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)

class Messages(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("userid", "private_message_id", name="uq_messages_user_private_msg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    userid: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="Telegram 用户ID")
    private_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="私聊消息ID")
    topic_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, comment="话题消息ID")
    spam: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否为垃圾消息")
    reason: Mapped[str] = mapped_column(String(256), nullable=False, comment="理由")
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, comment="消息时间")

class Users(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    userid: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True, comment="Telegram 用户ID")
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="Telegram 用户名")
    first_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="Telegram 用户名字")
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Telegram 用户姓氏")
    full_name: Mapped[str] = mapped_column(String(130), nullable=False, comment="Telegram 用户全名")
    language_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Telegram 用户语言代码")
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否为 Telegram  Premium 用户")
    topic: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, comment="对应的 Telegram 话题ID")
    first_active_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True, comment="首次对话时间")

class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    setting_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="设置名称")
    setting_value: Mapped[str] = mapped_column(String(256), nullable=False, comment="设置值")
