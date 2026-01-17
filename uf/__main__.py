from uf.src.job import TGBot
from uf.src.config import config

if __name__ == "__main__":
    bot = TGBot(
        config.telegram.token,
        config.telegram.topic_chat_id,
        config.telegram.admin_id,
        config.telegram.verify_ttl,
    )
    bot.run()