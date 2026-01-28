import traceback
import asyncio
from typing import Any, Literal, Sequence
from datetime import datetime
import signal
from contextlib import suppress

from telegram import MessageId, Update, Message, BotCommand, User
from telegram.ext import Application, CommandHandler, ExtBot, CallbackContext, JobQueue, MessageHandler, filters, MessageReactionHandler, AIORateLimiter
from telegram.constants import ChatType, ChatAction, BOT_API_VERSION, ParseMode
import telegram.error
from telegram_markdown_converter import convert_markdown

from uf.src.log import tg_log
from uf.src.verify import Visual, VerifyType
from uf.src.sql import engine, init_db, healthy
from uf.src.sql.repository import UFRepository
from uf.src.cache import DataCache
from uf.src.spam_detect import SpamDetector

class TopicGroupFilter(filters.MessageFilter):
    def __init__(self, topic_chat_id: int, admin_user_id: int) -> None:
        super().__init__()
        self.topic_chat_id = topic_chat_id
        self.admin_user_id = admin_user_id

    def filter(self, message: Message) -> bool:
        if not message.chat or not message.from_user:
            return False

        # 必须是超级群
        if message.chat.type != ChatType.SUPERGROUP:
            return False

        # 必须是指定群
        if message.chat.id != self.topic_chat_id:
            return False

        # 必须是管理员发的
        if message.from_user.id != self.admin_user_id:
            return False
        
        # 必须是话题群
        if not message.chat.is_forum:
            return False

        return True

# Application[
#     ExtBot[None],
#     CallbackContext[
#         ExtBot[None],
#         dict[Any, Any],
#         dict[Any, Any],
#         dict[Any, Any]
#     ],
#     dict[Any, Any],
#     dict[Any, Any],
#     dict[Any, Any],
#     JobQueue[
#         CallbackContext[
#             ExtBot[None],
#             dict[Any, Any],
#             dict[Any, Any],
#             dict[Any, Any]
#         ]
#     ]
# ]
BotData = dict[Any, Any]
ChatData = dict[Any, Any]
UserData = dict[Any, Any]
Context = CallbackContext[ExtBot[None], UserData, ChatData, BotData]
App = Application[ExtBot[None], Context, UserData, ChatData, BotData, JobQueue[Context]]

class MyBot:
    def __init__(self, token: str, topic_chat_id: int, admin_user_id: int, ttl: int) -> None:
        self.token: str = token
        self.topic_chat_id: int = topic_chat_id
        self.admin_user_id: int = admin_user_id
        self.ttl: int = ttl
        self.bot: App = self._init_bot()
        self.visual: Visual = Visual()
        self.cache: DataCache = DataCache()
        self.uf_repo: UFRepository = UFRepository()
        self.spamd: SpamDetector = SpamDetector()
        self.topic_filter = TopicGroupFilter(self.topic_chat_id, self.admin_user_id)

        self.str_bool_map: dict[str, bool] = {
            "true": True,
            "false": False,
        }

    def _init_bot(self) -> App:
        if not self.token or not self.topic_chat_id or not self.admin_user_id or self.ttl <= 0:
            raise ValueError("token, topic_chat_id, admin_user_id, ttl 不能为空")

        app = Application.builder()
        app.token(self.token)
        app.post_init(self._on_startup)
        app.post_shutdown(self._on_shutdown)
        app.concurrent_updates(8)
        app.rate_limiter(AIORateLimiter(max_retries=3))
        return app.build()

    async def _create_spam_topic(self, app: App) -> bool:
        """创建 Spam 消息话题"""
        spam_topic_str = await self.uf_repo.select_settings("spam_topic")
        if not spam_topic_str:
            spam_topic_raw = await app.bot.create_forum_topic(
                chat_id=self.topic_chat_id,
                name="被判定为 Spam 的消息"
            )
            self.spam_topic_id: int = spam_topic_raw.message_thread_id
            await self.uf_repo.insert_settings("spam_topic", str(self.spam_topic_id))
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="此话题用于存储被AI/关键词判定为 Spam 的消息\n"
                "对应存储在数据库中的消息数据会被定时清理",
                message_thread_id=self.spam_topic_id
            )
            tg_log.info("Spam 消息话题已创建")
            return True
        else:
            spam_topic = int(spam_topic_str)
            try:
                msg = await app.bot.send_message(
                    chat_id=self.topic_chat_id,
                    text="Test Message",
                    message_thread_id=spam_topic
                )
            except telegram.error.BadRequest:
                await app.bot.send_message(
                    chat_id=self.topic_chat_id,
                    text="未找到用于存储 Spam 消息的话题，请重启程序"
                )
                tg_log.error(f"配置的 topic_chat_id 中未找到用于存储 Spam 消息的话题: {spam_topic}")
                await self.uf_repo.delete_settings("spam_topic")
                return False
            except telegram.error.Forbidden as e:
                tg_log.error(f"自检中有操作被禁止: {e}")
                return False
            else:
                await msg.delete()
            self.spam_topic_id: int = spam_topic
            return True

    async def _bot_self_test(self, app: App, me: User):
        """自检"""
        (
            type_check,
            forum_check,
            admin_check,
            privacy_check,
            topics_check,
        ) = True, True, True, True, True
        tg_log.info("Bot 开始自检")
        await app.bot.send_message(
            chat_id=self.topic_chat_id,
            text="Bot 开始自检"
        )
        chat = await app.bot.get_chat(self.topic_chat_id)
        member = await app.bot.get_chat_member(self.topic_chat_id, me.id)
        privacy_disabled = me.can_read_all_group_messages
        is_admin = member.status in ("administrator", "creator")
        can_manage_topics = bool(getattr(member, "can_manage_topics", False))

        done_msg = "Bot 自检完成，没有任何错误，可正常使用"

        tg_log.debug(f"正在检查配置中指定的 topic_chat_id - {self.topic_chat_id} 是否符合要求")
        if chat.type != ChatType.SUPERGROUP:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="本群群组类型不符合要求，请升级成超级群后重启程序"
            )
            tg_log.error(f"配置的 topic_chat_id 中群组类型不符合要求，请升级成超级群后重启程序")
            type_check = False
        
        tg_log.debug(f"正在检查配置中指定的 topic_chat_id - {self.topic_chat_id} 是否开启话题模式")
        if not chat.is_forum:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="本群未开启话题模式，请开启后重启程序"
            )
            tg_log.error(f"配置的 topic_chat_id 中未开启话题模式，请开启后重启程序")
            forum_check = False
        
        tg_log.debug(f"正在检查配置中指定的 topic_chat_id - {self.topic_chat_id} 是否为管理员")
        if not is_admin:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="Bot 在本群不是管理员，请赋予管理员权限后重启程序"
            )
            tg_log.error(f"Bot 在配置的 topic_chat_id 中不是管理员，请赋予管理员权限后重启程序")
            admin_check = False
        
        tg_log.debug(f"正在检查 Bot 是否开启隐私模式")
        if not privacy_disabled:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="Bot 目前处于隐私模式，请关闭后重启程序"
            )
            tg_log.error(f"Bot 目前处于隐私模式，请关闭后重启程序")
            privacy_check = False
        
        tg_log.debug(f"正在检查配置中指定的 topic_chat_id - {self.topic_chat_id} 是否开启 管理话题/创建话题 权限")
        if not can_manage_topics:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="Bot 在本群缺少 管理话题 权限，请赋予权限后重启程序"
            )
            tg_log.error(f"Bot 在配置的 topic_chat_id 中缺少 管理话题 权限，请赋予权限后重启程序")
            topics_check = False
        else:
            topics_check: bool = await self._create_spam_topic(app)

        if all((type_check, forum_check, admin_check, privacy_check, topics_check)):
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text=done_msg
            )
            tg_log.info(done_msg)
        else:
            await app.bot.send_message(
                chat_id=self.topic_chat_id,
                text="Bot 自检失败，存在错误，请解决以上问题后重启程序"
            )
            tg_log.error("Bot 自检失败，存在错误，请解决后重启程序")

    async def create_topic(self, update: Update, context: Context) -> None:
        """创建新的 topic"""
        if not update.effective_user:
            raise ValueError("effective_user 为空")

        userid = update.effective_user.id

        userfullname = update.effective_user.full_name
        if len(userfullname) > 32:
            userfullname = update.effective_user.first_name[:16]

        is_premium = update.effective_user.is_premium or False

        topic_name = f"{userfullname} {userid}"

        final_msg = (
            f"用户ID {userid}\n"
            f"用户名字 {userfullname}\n"
            f"Premium 用户: {'是' if is_premium else '否'}"
        )

        existing = await self.uf_repo.select_user(userid, 'userid')
        if existing:
            self.cache.set_flag(userid, "to_topic", existing.topic)
            return

        try:
            topic = await context.bot.create_forum_topic(
                chat_id=self.topic_chat_id,
                name=topic_name,
            )
            await context.bot.send_message(
                chat_id=self.topic_chat_id,
                message_thread_id=topic.message_thread_id,
                text=final_msg,
            )
            await self.uf_repo.insert_user(
                userid=userid,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
                full_name=userfullname,
                language_code=update.effective_user.language_code,
                is_premium=is_premium,
                topic=topic.message_thread_id,
            )
        except Exception as e:
            await context.bot.send_message(chat_id=self.admin_user_id, text=f"为用户 {userfullname} ({userid}) 创建话题失败: {e}\n请检查是否已给予bot管理员权限")
            return

        self.cache.set_flag(userid, "to_topic", topic.message_thread_id)
        return

    async def forward_on_spam_topic(
            self,
            context: Context,
            from_chat_id: int,
            message_id: int,
            reason: str
        ) -> Message:
        msg: Message = await context.bot.forward_message(
            chat_id=self.topic_chat_id,
            message_thread_id=self.spam_topic_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )
        await msg.reply_text(reason)
        return msg

    async def keep_action(
            self,
            lock: asyncio.Lock,
            context: Context,
            chat_id: int,
            action: ChatAction,
            topic_id: int
        ):
        while lock.locked():
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=action,
                message_thread_id=topic_id,
            )
            await asyncio.sleep(4.5)

    async def _check_spam_with_typing(
            self,
            lock: asyncio.Lock,
            context: Context,
            topic_id: int,
            text: str,
        ) -> tuple[bool, str]:
        t = asyncio.create_task(
            self.keep_action(
                lock=lock,
                context=context,
                chat_id=self.topic_chat_id,
                action=ChatAction.TYPING,
                topic_id=topic_id,
            )
        )
        try:
            return await self.spamd.check_spam(text)
        finally:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t

    async def msg_to_topic(self, update: Update, context: Context) -> None:
        """将用户的消息发送到对应的话题"""
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        userid = update.effective_user.id
        lock = self.cache.get_user_lock(userid)

        async with lock:
            blocked = await self.uf_repo.select_block(userid)
            if blocked:
                await update.message.reply_text("你已被封禁")
                self.cache.set_flag(userid, VerifyType.BLOCK.value, blocked)
                return

            to_topic = self.cache.get_flag(userid, "to_topic", None)
            try:
                msg_count = self.cache.flood_message(userid, window=4)
                if msg_count > 10:
                    await update.message.reply_text("你已被封禁，原因: 刷屏")
                    self.cache.set_flag(userid, "block", True)
                    await self.uf_repo.insert_block(userid)
                    return
                if msg_count > 7:
                    await update.message.reply_text("请不要刷屏，否则将会被封禁")

                topic_id = to_topic
                if not topic_id:
                    topic = await self.uf_repo.select_user(userid, "userid")
                    if not topic:
                        await self.create_topic(update, context)
                        topic = await self.uf_repo.select_user(userid, "userid")
                        if not topic:
                            await update.message.reply_text("Bot错误，已不可用，请使用其它方式联系")
                            raise Exception("创建话题失败")

                    topic_id = topic.topic
                    self.cache.set_flag(userid, "to_topic", topic_id)

                msg_text = update.message.text
                if msg_text:
                    is_spam, reason = await self._check_spam_with_typing(
                        lock=lock,
                        context=context,
                        topic_id=topic_id,
                        text=msg_text,
                    )
                else:
                    is_spam, reason = False, "无文本消息"

                if is_spam:
                    to_topic_msg = await self.forward_on_spam_topic(
                        context=context,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id,
                        reason=reason
                    )
                    await self.uf_repo.insert_message(userid, update.message.message_id, to_topic_msg.message_id, is_spam, reason)
                    return

                to_topic_msg = await context.bot.copy_message(
                    chat_id=self.topic_chat_id,
                    message_thread_id=topic_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                )
                await self.uf_repo.insert_message(userid, update.message.message_id, to_topic_msg.message_id, is_spam, reason)
                return
            except telegram.error.TimedOut:
                await update.message.reply_text("Bot 超时，你的消息未传达\n你可以尝试重新发送或使用其它联系方式")

    async def _send_captcha_gif(
            self,
            update: Update,
            user_id: int,
            caption: str,
            mode: Literal["insert", "update"],
        ) -> None:
        if not update.message:
            return

        msg = await update.message.reply_text("请稍候")
        self.cache.set_flag(user_id, VerifyType.VERIFY.value, False)
        self.cache.set_flag(user_id, VerifyType.VERIFY_ATTEMPTS.value, 0)
        captcha_text, gif = await self.visual.async_generate_captcha_gif()
        if mode == "insert":
            await self.uf_repo.insert_verify(user_id, captcha_text, self.ttl)
        else:
            await self.uf_repo.update_verify_code(user_id, captcha_text, self.ttl)
        await msg.delete()
        await update.message.reply_animation(gif, caption=caption)

    async def _gif_verify(self, update: Update, first: bool = False) -> bool:
        """GIF验证"""
        if not update.message or not update.effective_user:
            return False

        if first:
            verify_msg = "你好，在发送消息前，请输入图中验证码（不区分大小写）"
        else:
            verify_msg = "你好，在成功发送消息前，请输入图中验证码（不区分大小写）"

        user_id = update.effective_user.id

        async with self.cache.get_user_lock(user_id):
            verify = await self.uf_repo.select_valid_verify(user_id)
            if not verify:
                await self._send_captcha_gif(
                    update=update,
                    user_id=user_id,
                    caption=verify_msg,
                    mode="insert",
                )
                return False
            if verify.verified:
                return True
            if verify.expires_at < datetime.now():
                await self._send_captcha_gif(
                    update=update,
                    user_id=user_id,
                    caption="验证码已过期，请重新输入（不区分大小写）",
                    mode="update",
                )
                return False
        
        return True

    async def _verify_attempts(self, update: Update, context: Context, text: str) -> None:
        """验证重试"""
        if not update.message or not update.effective_user:
            return
        
        user_id = update.effective_user.id

        verify = await self.uf_repo.select_valid_verify(user_id)
        if not verify:
            return
        
        if verify.verified:
            return

        async with self.cache.get_user_lock(user_id):
            attempts: int = self.cache.get_flag(user_id, VerifyType.VERIFY_ATTEMPTS.value, 0)
            if text.upper() == verify.code:
                await self.uf_repo.update_verified(user_id, True)
                self.cache.set_flag(user_id, VerifyType.VERIFY.value, True)
                self.cache.set_flag(user_id, VerifyType.VERIFY_ATTEMPTS.value, 0)
                await update.message.reply_text("验证已通过，你可以发送消息了")
                await self.create_topic(update, context)
                return
            else:
                attempts += 1
                self.cache.set_flag(user_id, VerifyType.VERIFY_ATTEMPTS.value, attempts)
                remaining: int = 3 - attempts
                if remaining > 0:
                    await update.message.reply_text(f"验证码错误，你还有 {remaining} 次机会。")
                    return
                else:
                    await update.message.reply_text("验证码错误次数过多，你已被封禁。")
                    self.cache.set_flag(user_id, VerifyType.VERIFY.value, False)
                    await self.uf_repo.insert_block(user_id)
                    self.cache.set_flag(user_id, "block", True)
                    return

    async def _resolve_userid_by_topic(self, topic_id: int) -> int | None:
        to_user = self.cache.get_topic(topic_id, "to_user")
        if to_user:
            return to_user

        user_data = await self.uf_repo.select_user(topic_id, "topic")
        if not user_data:
            return None

        self.cache.set_topic(topic_id, "to_user", user_data.userid)
        return user_data.userid

    async def _forward_topic_message_to_user(
            self,
            context: Context,
            topic_id: int,
            to_user: int,
            topic_message_id: int,
        ) -> None:
        lock = self.cache.get_user_lock(to_user)
        async with lock:
            to_private_msg = await self.topic_msg_to_private(
                context=context,
                chat_id=to_user,
                message_thread_id=topic_id,
                from_chat_id=self.topic_chat_id,
                message_id=topic_message_id,
            )
            if not to_private_msg:
                return
            private_message_id = to_private_msg.message_id
            await self.uf_repo.insert_message(
                to_user,
                private_message_id,
                topic_message_id,
                False,
                "管理员消息",
            )

    async def topic_msg_to_private(
            self,
            context: Context,
            chat_id: int,
            message_thread_id: int,
            from_chat_id: int,
            message_id: int
    ) -> MessageId | None:
        """私有方法，统一发送函数"""
        try:
            msg = await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
        except telegram.error.Forbidden:
            await context.bot.send_message(
                chat_id=self.topic_chat_id,
                text="消息发送失败，对方把你的bot拉黑了",
                message_thread_id=message_thread_id,
            )
            return
        return msg

    async def handle_topic_message(self, update: Update, context: Context) -> None:
        """处理话题消息"""
        if not update.message or not update.message.message_thread_id:
            return
        
        topic_id = update.message.message_thread_id
        to_user = await self._resolve_userid_by_topic(topic_id)
        if not to_user:
            await update.message.reply_text("对应的用户不存在")
            return

        await self._forward_topic_message_to_user(
            context=context,
            topic_id=topic_id,
            to_user=to_user,
            topic_message_id=update.message.message_id,
        )
        return

    async def handle_private_message(self, update: Update, context: Context) -> None:
        """处理私聊消息"""
        if not update.message or not update.effective_user:
            return

        user_id = update.effective_user.id
        blocked = self.cache.get_flag(user_id, VerifyType.BLOCK.value)
        if blocked:
            await update.message.reply_text("你已被封禁")
            return
        verified = self.cache.get_flag(user_id, VerifyType.VERIFY.value)

        if verified is None:
            verified = await self.uf_repo.select_verified(user_id)
            self.cache.set_flag(user_id, VerifyType.VERIFY.value, verified)

        if verified:
            await self.msg_to_topic(update, context)
            return

        text = (update.message.text or "").strip()

        if not await self._gif_verify(update):
            return

        await self._verify_attempts(update, context, text)
        return

    async def _ensure_single_reaction(
            self,
            context: Context,
            warn_chat_id: int,
            warn_text: str,
            reaction: Sequence[Any],
        ) -> list[Any]:
        if len(reaction) <= 1:
            return list(reaction)

        await context.bot.send_message(
            chat_id=warn_chat_id,
            text=warn_text,
        )
        return [reaction[0]]

    async def handle_reaction_message(self, update: Update, context: Context) -> None:
        """处理表态"""
        if not update.message_reaction:
            return
        if not update.message_reaction.chat:
            return

        chat_id = update.message_reaction.chat.id
        msg_id = update.message_reaction.message_id
        chat_type = update.message_reaction.chat.type

        if chat_type == ChatType.PRIVATE:
            msg_data = await self.uf_repo.select_message(msg_id, topic_mode=False, userid=chat_id)
            if not msg_data:
                return
            reaction = update.message_reaction.new_reaction
            reaction = await self._ensure_single_reaction(
                context=context,
                warn_chat_id=chat_id,
                warn_text="虽然你可以多次 reaction，但管理员只能收到第一个 reaction",
                reaction=reaction,
            )
            await context.bot.set_message_reaction(
                chat_id=self.topic_chat_id,
                message_id=msg_data.topic_message_id,
                reaction=reaction,
            )
            return

        if chat_id != self.topic_chat_id:
            return

        msg_data = await self.uf_repo.select_message(msg_id, topic_mode=True)
        if not msg_data:
            return
        reaction = update.message_reaction.new_reaction
        reaction = await self._ensure_single_reaction(
            context=context,
            warn_chat_id=self.topic_chat_id,
            warn_text="虽然你可以多次 reaction，但用户只能收到第一个 reaction",
            reaction=reaction,
        )
        await context.bot.set_message_reaction(
            chat_id=msg_data.userid,
            message_id=msg_data.private_message_id,
            reaction=reaction,
        )

    async def handle_topic_edited_message(self, update: Update, context: Context) -> None:
        """处理被编辑的消息（话题）"""
        if not update.edited_message or not update.edited_message.text:
            return
        
        msg_id = update.edited_message.message_id
        msg_data = await self.uf_repo.select_message(msg_id, topic_mode=True)
        if not msg_data:
            return
        
        await context.bot.edit_message_text(
            chat_id=msg_data.userid,
            message_id=msg_data.private_message_id,
            text=update.edited_message.text
        )
    
    async def handle_private_edited_message(self, update: Update, context: Context) -> None:
        """处理被编辑的消息（私聊）"""
        if not update.edited_message or not update.edited_message.text or not update.effective_user:
            return
        
        msg_id = update.edited_message.message_id
        userid = update.effective_user.id
        msg_new_text = update.edited_message.text
        msg_data = await self.uf_repo.select_message(msg_id, topic_mode=False, userid=userid)
        user_data = await self.uf_repo.select_user(userid, 'userid')
        if not msg_data or not user_data:
            return

        lock = self.cache.get_user_lock(userid)
        async with lock:
            is_spam, reason = await self._check_spam_with_typing(
                lock=lock,
                context=context,
                topic_id=user_data.topic,
                text=msg_new_text,
            )

            if is_spam:
                await self.forward_on_spam_topic(
                    context=context,
                    from_chat_id=userid,
                    message_id=msg_id,
                    reason=reason,
                )
                await context.bot.send_message(
                    chat_id=userid,
                    text=f"消息已被驳回，原因: {reason}",
                    reply_to_message_id=msg_id,
                )
                return

            await context.bot.edit_message_text(
                chat_id=self.topic_chat_id,
                message_id=msg_data.topic_message_id,
                text=msg_new_text
            )

    async def _start(self, update: Update, context: Context) -> None:
        """处理 /start 命令"""
        if not update.message:
            return
        await self._gif_verify(update, first=True)
        return

    async def _delete(self, update: Update, context: Context) -> None:
        """处理 /d 命令"""
        if not update.message or not update.effective_user or not update.effective_chat:
            return
        
        if not update.message.reply_to_message or update.message.reply_to_message.message_id == update.message.message_thread_id:
            await update.message.reply_text("请回复一个消息")
            return
        
        userid = update.effective_user.id
        msg_id = update.message.reply_to_message.message_id

        if update.effective_chat.type == ChatType.PRIVATE:
            msg = await self.uf_repo.select_message(msg_id, topic_mode=False, userid=userid)
        elif update.effective_chat.is_forum:
            msg = await self.uf_repo.select_message(msg_id, topic_mode=True)
        else:
            await update.message.reply_text("无效的消息对象")
            return

        if not msg:
            await update.message.reply_text("回复的消息目前已不可删除")
            return
        
        await context.bot.delete_message(msg.userid, msg.private_message_id)
        await context.bot.delete_message(self.topic_chat_id, msg.topic_message_id)
        await self.uf_repo.delete_message(msg)
        return

    async def _ban(self, update: Update, context: Context) -> None:
        """处理 /ban 命令"""
        if not update.message:
            return

        if not update.message.message_thread_id: # 在 General 发消息时则为空
            await update.message.reply_text("未指定任何用户")
            return

        topic_id = update.message.message_thread_id
        user_data = await self.uf_repo.select_user(topic_id, "topic")

        if not user_data:
            await update.message.reply_text("此用户无效")
            return

        pinned_msg = await update.message.reply_text("此用户已被封禁")
        await pinned_msg.pin(disable_notification=True)

        async with self.cache.get_user_lock(user_data.userid):
            await self.uf_repo.insert_block(user_data.userid, pinned_msg.message_id)
            self.cache.set_flag(user_data.userid, "block", True)
        return
    
    async def _unban(self, update: Update, context: Context) -> None:
        """处理 /unban 命令"""
        if not update.message:
            return
        
        if not update.message.message_thread_id: # 在 General 发消息时则为空
            await update.message.reply_text("未指定任何用户")
            return
        
        topic_id = update.message.message_thread_id
        user_data = await self.uf_repo.select_user(topic_id, "topic")
        if not user_data:
            await update.message.reply_text("此用户无效")
            return
        
        block_data = await self.uf_repo.select_block_raw(user_data.userid)
        if not block_data:
            await update.message.reply_text("此用户未被拉黑")
            return

        if block_data.pinned_msg_id:
            await context.bot.delete_message(self.topic_chat_id, block_data.pinned_msg_id)

        async with self.cache.get_user_lock(user_data.userid):
            await self.uf_repo.delete_block(block_data)
            self.cache.set_flag(user_data.userid, "block", False)
        await update.message.reply_text("用户已解封")
        return

    async def _info_self(self, update: Update, context: Context) -> None:
        """获取机器人本身的信息"""
        if not update.message:
            return
        bot = context.bot
        me = await bot.get_me()

        database_status, database_error = await healthy()
        if database_status:
            db_text = "正常"
            (
                verified_cnt,
                blocked_cnt,
                topics_cnt,
                total_cnt,
                spam_cnt
            ) = await asyncio.gather(
                self.uf_repo.count_verified_users(),
                self.uf_repo.count_blocked_users(),
                self.uf_repo.count_topics(),
                self.uf_repo.count_messages_total(),
                self.uf_repo.count_spam_messages(),
            )
            database_msg = (
                f"\n> 通过用户数: {verified_cnt}\n"
                f"> 封禁用户数: {blocked_cnt}\n"
                f"> 创建话题数: {topics_cnt}\n"
                f"> 保存消息数: {total_cnt}\n"
                f"> 垃圾消息数: {spam_cnt}\n"
            )
        else:
            db_text = f"异常: {database_error}"
            database_msg = "\n"


        uptime = datetime.now() - self.cache.startup_time
        uptime_str = (
            f"{uptime.days}天 "
            f"{uptime.seconds // 3600}小时 "
            f"{(uptime.seconds % 3600) // 60}分钟 "
            f"{uptime.seconds % 60}秒"
        )

        (
            user_locks_size,
            user_data_size,
            topic_data_size,
            user_message_time_queues_size,
        ) = self.cache.get_cache_size()

        final_msg = (
            f"Bot 信息: \n"
            f"> Bot 名称: {me.full_name}\n"
            f"> Bot ID: {me.id}\n"
            f"> Bot 用户名: @{me.username}\n"
            f"> Bot 运行时间: {uptime_str}\n"
            f"数据库信息: \n"
            f"> 数据库后端: {engine.dialect.name}\n"
            f"> 数据库状态: {db_text}"
            f"{database_msg}"
            f"缓存状态: \n"
            f"> 用户锁占用: {user_locks_size}\n"
            f"> 用户数据占用: {user_data_size}\n"
            f"> 话题数据占用: {topic_data_size}\n"
            f"> 用户消息时间队列占用: {user_message_time_queues_size}\n"
            "Copyright (C) 2026 Azusa-Mikan"
        )
        await update.message.reply_text(convert_markdown(final_msg), parse_mode=ParseMode.MARKDOWN_V2)

    async def _info_user(self, update: Update) -> None:
        """获取用户信息"""
        if not update.message or not update.message.message_thread_id:
            return

        topicid = update.message.message_thread_id
        user_data = await self.uf_repo.select_user(topicid, "topic")
        if not user_data:
            await update.message.reply_text("此用户无效")
            return
        block = await self.uf_repo.select_block(user_data.userid)
        is_blocked = "是" if block else "否"

        user_name = f"@{user_data.username}" if user_data.username else "无"

        final_msg = (
            f"用户信息: \n"
            f"> 用户ID: {user_data.userid}\n"
            f"> 用户名: {user_name}\n"
            f"> 语言代码: {user_data.language_code}\n"
            f"> 是否为 Premium 用户: {'是' if user_data.is_premium else '否'}\n"
            f"> 通过验证时间: {user_data.first_active_time}\n"
            f"> 是否被封禁: {is_blocked}"
        )
        await update.message.reply_text(convert_markdown(final_msg), parse_mode=ParseMode.MARKDOWN_V2)

    async def _info_message(self, update: Update) -> None:
        """获取消息详细信息"""
        if not update.message or not update.message.reply_to_message:
            return
        
        msg_data = await self.uf_repo.select_message(
            update.message.reply_to_message.message_id,
            True
        )
        if not msg_data:
            await update.message.reply_text("此消息无效或在数据库中不存在")
            return
        
        final_msg = (
            f"消息信息: \n"
            f"> 消息ID: {msg_data.topic_message_id}\n"
            f"> 对应的私聊ID: {msg_data.private_message_id}\n"
            f"> 消息发送时间: {msg_data.time}\n"
            f"> 是否为垃圾消息: {'是' if msg_data.spam else '否'}\n"
            f"> {'是' if msg_data.spam else '不是'}垃圾消息的理由: {msg_data.reason}"
        )
        await update.message.reply_text(convert_markdown(final_msg), parse_mode=ParseMode.MARKDOWN_V2)

    async def _info_route(self, update: Update, context: Context) -> None:
        """处理 info 命令"""
        if not update.message:
            return
        
        if update.message.message_thread_id is None:
            await self._info_self(update, context)
            return
        
        reply = update.message.reply_to_message
        if reply and reply.message_id != update.message.message_thread_id:
            await self._info_message(update)
            return

        await self._info_user(update)
        return

    async def _verify(self, update: Update, context: Context) -> None:
        """处理 verify 命令"""
        if not update.message:
            return
        
        if not update.message.message_thread_id: # 在 General 发消息时则为空
            await update.message.reply_text("未指定任何用户")
            return
        
        args = context.args
        if not args or len(args) != 1:
            await update.message.reply_text(
                "用法: /verify <true/false>"
            )
            return
        
        topicid = update.message.message_thread_id
        user_data = await self.uf_repo.select_user(topicid, "topic")
        if not user_data:
            await update.message.reply_text("此用户无效")
            return

        bool_arg = args[0].strip().lower()
        if bool_arg not in self.str_bool_map:
            await update.message.reply_text(
                "用法: /verify <true/false>"
            )
            return
        verified = self.str_bool_map[bool_arg]
        if not verified:
            self.cache.set_flag(user_data.userid, VerifyType.VERIFY.value, False)
            await self.uf_repo.update_verified(user_data.userid, False)
            await context.bot.send_message(
                user_data.userid,
                "管理员已清除了你的验证状态，"
                "请重新验证"
            )
        else:
            self.cache.set_flag(user_data.userid, VerifyType.VERIFY.value, True)
            await self.uf_repo.update_verified(user_data.userid, True)
            await context.bot.send_message(
                user_data.userid,
                "管理员手动通过了你的验证，"
                "你可以直接发送消息"
            )

    async def _on_error(self, app: object, context: Context) -> None:
        tg_log.exception(f"发生错误: {context.error}", exc_info=context.error)
        await context.bot.send_message(
            chat_id=self.topic_chat_id,
            text=f"发生错误: {context.error}\n请检查日志",
        )
    
    async def _on_shutdown(self, app: App) -> None:
        await engine.dispose()
        tg_log.info("Bot 已关闭")

    def register_handlers(self) -> None:
        self.bot.add_error_handler(self._on_error)
        self.bot.add_handler(CommandHandler("start", self._start, filters=filters.ChatType.PRIVATE))
        self.bot.add_handler(CommandHandler("help", self._help))
        self.bot.add_handler(CommandHandler("d", self._delete))
        self.bot.add_handler(CommandHandler("ban", self._ban, filters=self.topic_filter & filters.User(self.admin_user_id)))
        self.bot.add_handler(CommandHandler("unban", self._unban, filters=self.topic_filter & filters.User(self.admin_user_id)))
        self.bot.add_handler(CommandHandler("info", self._info_route, filters=self.topic_filter & filters.User(self.admin_user_id)))
        self.bot.add_handler(CommandHandler("verify", self._verify, filters=self.topic_filter & filters.User(self.admin_user_id)))
        self.bot.add_handler(MessageHandler(self.topic_filter & filters.UpdateType.EDITED_MESSAGE, self.handle_topic_edited_message))
        self.bot.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.UpdateType.EDITED_MESSAGE, self.handle_private_edited_message))
        self.bot.add_handler(MessageHandler(self.topic_filter & ~filters.UpdateType.EDITED_MESSAGE, self.handle_topic_message))
        self.bot.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, self.handle_private_message))
        self.bot.add_handler(MessageReactionHandler(self.handle_reaction_message))

    async def _set_command(self, app: App) -> None:
        bot_command = [
            BotCommand("start", "开始聊天"),
            BotCommand("help", "获取帮助"),
            BotCommand("d", "撤回消息"),
            BotCommand("ban", "封禁用户"),
            BotCommand("unban", "解封用户"),
            BotCommand("info", "获取用户信息/消息细节/Bot信息"),
            BotCommand("verify", "手动验证用户"),
        ]
        tg_log.info(f"注册了 {len(bot_command)} 个命令")
        await app.bot.set_my_commands(bot_command)

    async def _help(self, update: Update, context: Context) -> None:
        """处理 /help 命令"""
        if not update.message:
            return
        await update.message.reply_text(
            "/start - 开始验证（验证通过则无返回）\n"
            "/help - 显示此信息\n"
            "/d - 撤回一个消息（必须回复一个消息）\n"
            "/ban - 封禁用户（仅管理员）\n"
            "/unban - 解封用户（仅管理员）\n"
            "/info - 获取用户信息/消息细节/Bot信息（仅管理员）\n"
            "/verify - 手动验证用户（仅管理员）\n"
            "发送验证码 - 验证\n"
            "发送消息 - 消息将转发到所有者\n\n"
            "Copyright (C) 2026 Azusa-Mikan"
        )
        return

    async def _on_startup(self, app: App) -> None:
        try:
            await init_db()
            me: User = await app.bot.get_me()
            tg_log.info(f"Bot 已启动 - {me.full_name} - {me.id}")
            await self._bot_self_test(app, me)
            tg_log.info(f"Telegram Bot API 版本 - {BOT_API_VERSION}")
            await self._set_command(app)
            self.bot_id: int = me.id
        except Exception as e:
            tg_log.exception("Bot 启动失败")
            raise RuntimeError("启动失败，请检查网络连接或数据库配置") from e

    def stop(self, signum: int, frame) -> None:
        tg_log.info("Bot 关闭中 - 请稍候")
        tg_log.debug(f"信号: {signum}")
        tg_log.debug(f"当前栈信息: {traceback.format_stack(frame)}")
        self.bot.stop_running()

    def run(self) -> None:
        tg_log.info("Bot 启动中")
        self.register_handlers()
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        self.bot.run_polling(
            stop_signals=None,
            allowed_updates=Update.ALL_TYPES,
        )
