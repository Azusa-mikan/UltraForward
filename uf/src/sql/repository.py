from datetime import datetime, timedelta

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from uf.src.sql import SessionLocal
from uf.src.sql.model import Verify, Block, Messages, Users, RuntimeSettings

from typing import Any, AsyncIterator, Literal
from contextlib import asynccontextmanager

class UFRepository:
    @asynccontextmanager
    async def _on_session(self) -> AsyncIterator[AsyncSession]:
        async with SessionLocal() as session:
            async with session.begin():
                yield session

    @asynccontextmanager
    async def _on_session_readonly(self) -> AsyncIterator[AsyncSession]:
        async with SessionLocal() as session:
            yield session
    
    async def _flush_nested_ignore_integrity(self, conn: AsyncSession) -> bool:
        """
        尝试在嵌套事务中刷新会话，忽略完整性错误。
        
        Args:
            conn (AsyncSession): 异步数据库会话
        
        Returns:
            bool: flush 是否成功（成功不代表已提交；提交由外层事务控制）
        """
        try:
            async with conn.begin_nested():
                await conn.flush()
            return True
        except IntegrityError:
            return False
    
    async def _add_and_flush_nested_ignore_integrity(self, conn: AsyncSession, entity: Any) -> bool:
        """
        尝试在嵌套事务中添加实体并刷新会话，忽略完整性错误。
        
        Args:
            conn (AsyncSession): 异步数据库会话
            entity (Any): 要添加的实体对象
        
        Returns:
            bool: flush 是否成功（成功不代表已提交；提交由外层事务控制）
        """
        try:
            async with conn.begin_nested():
                conn.add(entity)
                await conn.flush()
            return True
        except IntegrityError:
            try:
                conn.expunge(entity)
            except Exception:
                pass
            return False

    async def insert_verify(self, userid: int, code: str, ttl_seconds: int) -> None:
        """
        插入用户验证记录
        
        Args:
            userid (int): 用户ID
            code (str): 验证码
            ttl_seconds (int): 验证码过期时间（秒）
        """
        expires_at: datetime = datetime.now() + timedelta(seconds=ttl_seconds)
        async with self._on_session() as conn:
            stmt = select(Verify).where(Verify.userid == userid)
            result = await conn.execute(stmt)
            entity = result.scalar_one_or_none()
            if not entity:
                entity = Verify(
                    userid=userid,
                    code=code,
                    expires_at=expires_at,
                    verified=False,
                )
                conn.add(entity)
            else:
                entity.code = code
                entity.expires_at = expires_at
                entity.verified = False

            await conn.flush()

    async def select_valid_verify(self, userid: int) -> Verify | None:
        """
        根据用户ID选择有效验证记录
        
        Args:
            userid (int): 用户ID
        
        Returns:
             
            Verify | None: 如果找到有效验证记录则返回Verify对象，否则返回None
        """
        async with self._on_session_readonly() as conn:
            stmt = select(Verify).where(Verify.userid == userid)
            result = await conn.execute(stmt)
            return result.scalar_one_or_none()

    async def update_verified(self, userid: int, verified: bool) -> None:
        """
        更新用户验证状态
        
        Args:
            userid (int): 用户ID
            verified (bool): 验证状态
        """
        async with self._on_session() as conn:
            stmt = select(Verify).where(Verify.userid == userid)
            result = await conn.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity is not None:
                entity.verified = verified

    async def select_verified(self, userid: int) -> bool:
        """
        检查用户是否通过验证
        
        Args:
            userid (int): 用户ID
        
        Returns:
            bool: 如果用户通过验证则返回True，否则返回False
        """
        async with self._on_session_readonly() as conn:
            stmt = select(Verify).where(Verify.userid == userid)
            result = await conn.execute(stmt)
            re = result.scalar_one_or_none()

            if not re:
                return False

            return re.verified

    async def update_verify_code(self, userid: int, code: str, ttl_seconds: int) -> None:
        """
        更新用户验证记录的验证码
        
        Args:
            userid (int): 用户ID
            code (str): 新的验证码
            ttl_seconds (int): 验证码过期时间（秒）
        """
        async with self._on_session() as conn:
            stmt = select(Verify).where(Verify.userid == userid)
            result = await conn.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity is not None:
                entity.code = code
                entity.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

    async def insert_user(
            self,
            userid: int,
            username: str | None,
            first_name: str,
            last_name: str | None,
            full_name: str,
            language_code: str | None,
            is_premium: bool,
            topic: int,
        ) -> None:
        """
        插入用户主题映射关系
        
        Args:
            userid (int): 用户ID
            username (str | None): 用户名，可能为空
            first_name (str): 用户的名字
            last_name (str | None): 用户的姓氏，可能为空
            full_name (str): 名字 + 姓氏
            language_code (str | None): 语言代码，可能为空
            is_premium (bool): 是否为大会员用户
            topic (int): 映射的主题ID
        """
        async with self._on_session() as conn:
            stmt = select(Users).where(Users.userid == userid)
            result = await conn.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return

            entity = Users(
                userid=userid,
                username=username,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                language_code=language_code,
                is_premium=is_premium,
                topic=topic,
                first_active_time=datetime.now(),
            )
            if not await self._add_and_flush_nested_ignore_integrity(conn, entity):
                return

    async def select_user(self, id: int, type: Literal['userid', 'topic']) -> Users | None:
        """
        根据用户ID或话题ID获取映射关系
        
        Args:
            id (int): 用户ID或话题ID，根据type参数确定是用户ID还是话题ID
            type (Literal['userid', 'topic']): 映射类型，'userid' 表示用户ID，'topic' 表示话题消息
        
        Returns:
             
            Users | None: 如果找到映射关系则返回Users对象，否则返回None
        """
        async with self._on_session_readonly() as conn:
            if type == 'userid':
                stmt = select(Users).where(Users.userid == id)
            else:
                stmt = select(Users).where(Users.topic == id)
            result = await conn.execute(stmt)
            return result.scalar_one_or_none()

    async def insert_block(self, userid: int, pinned_msg_id: int | None = None) -> None:
        """
        封禁用户
        
        Args:
            userid (int): 用户ID
            pinned_msg_id (int | None): 如果是手动封禁，记录置顶的被提示封禁的消息ID，默认值为None
        """
        async with self._on_session() as conn:
            stmt = select(Block).where(Block.userid == userid)
            result = await conn.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                if pinned_msg_id is not None and existing.pinned_msg_id is None:
                    existing.pinned_msg_id = pinned_msg_id
                    await self._flush_nested_ignore_integrity(conn)
                return

            entity = Block(
                userid=userid,
                pinned_msg_id=pinned_msg_id,
            )
            await self._add_and_flush_nested_ignore_integrity(conn, entity)
            return

    async def select_block(self, userid: int) -> bool:
        """
        检查用户是否被封禁
        
        Args:
            userid (int): 用户ID
        
        Returns:
            bool: 如果用户被封禁则返回True，否则返回False
        """
        async with self._on_session_readonly() as conn:
            stmt = select(Block).where(Block.userid == userid)
            result = await conn.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def select_block_raw(self, userid: int) -> Block | None:
        """
        获取封禁用户数据
        
        Args:
            userid (int): 用户ID
        
        Returns:
             
            Block | None: 如果找到映射关系则返回Block对象，否则返回None
        """
        async with self._on_session_readonly() as conn:
            stmt = select(Block).where(Block.userid == userid)
            result = await conn.execute(stmt)
            return result.scalar_one_or_none()

    async def delete_block(self, msg: Block) -> None:
        async with self._on_session() as conn:
            await conn.delete(msg)

    async def insert_message(self, userid: int, private_msg_id: int, topic_msg_id: int, spam: bool, reason: str) -> None:
        """
        插入消息到数据库

        Args:
            userid (int): 用户ID
            private_msg_id (int): 私聊消息ID
            topic_msg_id (int): 话题消息ID
        """
        async with self._on_session() as conn:
            entity = Messages(
                userid=userid,
                private_message_id=private_msg_id,
                topic_message_id=topic_msg_id,
                spam=spam,
                reason=reason,
                time=datetime.now(),
            )
            ok = await self._add_and_flush_nested_ignore_integrity(conn, entity)
            if ok:
                return

            stmt_by_topic = select(Messages).where(Messages.topic_message_id == topic_msg_id)
            existing_by_topic = (await conn.execute(stmt_by_topic)).scalar_one_or_none()
            if existing_by_topic is not None:
                return

            stmt_by_private = select(Messages).where(
                Messages.userid == userid,
                Messages.private_message_id == private_msg_id,
            )
            existing_by_private = (await conn.execute(stmt_by_private)).scalar_one_or_none()
            if existing_by_private is not None:
                return

            raise RuntimeError("insert_message failed but no existing row found")

    async def select_message(self, msg_id: int, topic_mode: bool, userid: int | None = None) -> Messages | None:
        """
        根据用户ID和私聊消息ID或仅话题消息ID获取对应的消息数据
        
        Args:
            msg_id (int): 私聊消息ID或话题消息ID
            topic_mode (bool): 是否为话题消息模式，True表示话题消息ID，False表示私聊消息ID
            userid (int | None, optional): 用户ID，仅在topic_mode为False时需要提供，默认值为None
        
        Returns:
             
            Messages | None: 如果找到消息记录则返回Messages对象，否则返回None
        """
        async with self._on_session_readonly() as conn:
            if topic_mode:
                stmt = select(Messages).where(
                    Messages.topic_message_id == msg_id
                )
            else:
                stmt = select(Messages).where(
                    Messages.userid == userid,
                    Messages.private_message_id == msg_id
                )

            result = await conn.execute(stmt)
            return result.scalar_one_or_none()

    async def delete_message(self, block_data: Messages) -> None:
        """
        删除数据库中的消息记录
        
        Args:
            block_data (Messages): 要删除的消息记录对象
        """
        async with self._on_session() as conn:
            await conn.delete(block_data)
    
    async def delete_message_on_days(self, days: int) -> None:
        """
        删除数据库中指定天数前的消息记录
        
        Args:
            days (int): 要删除的天数
        """
        async with self._on_session() as conn:
            stmt = delete(Messages).where(
                Messages.time < datetime.now() - timedelta(days=days)
            )
            await conn.execute(stmt)
    
    async def insert_settings(self, key: str, value: str) -> None:
        """
        插入运行时设置到数据库
        
        Args:
            key (str): 设置键名
            value (str): 设置值
        """
        async with self._on_session() as conn:
            entity = RuntimeSettings(
                setting_key=key,
                setting_value=value,
            )
            await self._add_and_flush_nested_ignore_integrity(conn, entity)
    
    async def select_settings(self, key: str) -> str | None:
        """
        根据设置键名获取运行时设置
        
        Args:
            key (str): 设置键名
        
        Returns:
             
            str | None: 如果找到设置则返回设置值，否则返回None
        """
        async with self._on_session_readonly() as conn:
            stmt = select(RuntimeSettings).where(RuntimeSettings.setting_key == key)
            result = await conn.execute(stmt)
            runtime_settings = result.scalar_one_or_none()
            if runtime_settings is None:
                return None
            return runtime_settings.setting_value
    
    async def delete_settings(self, key: str) -> None:
        """
        根据设置名称删除运行时设置
        
        Args:
            key (str): 设置键名
        """
        async with self._on_session() as conn:
            stmt = delete(RuntimeSettings).where(RuntimeSettings.setting_key == key)
            await conn.execute(stmt)

    async def count_verified_users(self) -> int:
        """
        统计数据库中已验证用户的数量
        
        Returns:
            int: 已验证用户的数量
        """
        async with self._on_session_readonly() as conn:
            stmt = (
                select(func.count())
                .select_from(Verify)
                .where(Verify.verified.is_(True))
            )
            return (await conn.execute(stmt)).scalar_one()
    
    async def count_blocked_users(self) -> int:
        """
        统计数据库中被封禁用户的数量
        
        Returns:
            int: 被封禁用户的数量
        """
        async with self._on_session_readonly() as conn:
            stmt = select(func.count()).select_from(Block)
            return (await conn.execute(stmt)).scalar_one()
    
    async def count_topics(self) -> int:
        """
        统计数据库中话题的数量
        
        Returns:
            int: 话题的数量
        """
        async with self._on_session_readonly() as conn:
            stmt = select(func.count()).select_from(Users)
            return (await conn.execute(stmt)).scalar_one()
    
    async def count_messages_total(self) -> int:
        """
        统计数据库中所有消息的总数量
        
        Returns:
            int: 所有消息的总数量
        """
        async with self._on_session_readonly() as conn:
            stmt = select(func.count()).select_from(Messages)
            return (await conn.execute(stmt)).scalar_one()
    
    async def count_messages_by_user(self, userid: int) -> int:
        """
        统计数据库中指定用户的所有消息数量
        
        Args:
            userid (int): 用户ID
        
        Returns:
            int: 指定用户的所有消息数量
        """
        async with self._on_session_readonly() as conn:
            stmt = (
                select(func.count())
                .select_from(Messages)
                .where(Messages.userid == userid)
            )
            return (await conn.execute(stmt)).scalar_one()
    
    async def count_spam_messages(self) -> int:
        """
        统计数据库中被标记为垃圾消息的数量
        
        Returns:
            int: 被标记为垃圾消息的数量
        """
        async with self._on_session_readonly() as conn:
            stmt = (
                select(func.count())
                .select_from(Messages)
                .where(Messages.spam.is_(True))
            )
            return (await conn.execute(stmt)).scalar_one()
