from datetime import time
from typing import Any
from telegram.ext import Application, ExtBot, CallbackContext, JobQueue
from uf.src.bot import MyBot

BotData = dict[Any, Any]
ChatData = dict[Any, Any]
UserData = dict[Any, Any]
Context = CallbackContext[ExtBot[None], UserData, ChatData, BotData]
App = Application[ExtBot[None], Context, UserData, ChatData, BotData, JobQueue[Context]]

class TGBot(MyBot):
    async def _cleanup_cache_job(self, context: Context) -> None:
        self.cache.clear_topic_all()
        self.cache.clear_user_all()

    async def _cleanup_db_job(self, context: Context) -> None:
        await self.uf_repo.delete_message_on_days(2)


    async def _on_startup(self, app: App) -> None:
        await super()._on_startup(app) # 继承父类的逻辑
        if not app.job_queue:
            return

        app.job_queue.run_daily(self._cleanup_cache_job, time=time(0, 0), name="cleanup_cache")
        app.job_queue.run_daily(self._cleanup_db_job, time=time(0, 0), name="cleanup_db")
