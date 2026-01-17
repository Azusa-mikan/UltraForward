import logging
from logging.handlers import RotatingFileHandler
import sys
import colorlog
from pathlib import Path
from uf.src.config import config

log_path = Path(__file__).parents[2] / "logs"
if not log_path.exists():
    log_path.mkdir(exist_ok=True)

log_level_map: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

date_format = "%Y-%m-%d %H:%M:%S"

file_formatter = logging.Formatter(
    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt=date_format
)

console_formatter = colorlog.ColoredFormatter(
    fmt="%(asctime)s - %(name)s - %(log_color)s%(levelname)s%(reset)s - %(message)s",
    datefmt=date_format,
    log_colors={
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    },
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(log_level_map.get(config.log_level.upper(), logging.INFO))
console_handler.setFormatter(console_formatter)

file_handler_tg = RotatingFileHandler(
    filename=log_path / "bot.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=0,
    encoding="utf-8",
)
file_handler_tg.setLevel(logging.DEBUG)
file_handler_tg.setFormatter(file_formatter)

file_handler_sql = RotatingFileHandler(
    filename=log_path / "sql.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=0,
    encoding="utf-8",
)
file_handler_sql.setLevel(logging.DEBUG)
file_handler_sql.setFormatter(file_formatter)

file_handler_cache = RotatingFileHandler(
    filename=log_path / "cache.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=0,
    encoding="utf-8",
)
file_handler_cache.setLevel(logging.DEBUG)
file_handler_cache.setFormatter(file_formatter)

file_handler_ai = RotatingFileHandler(
    filename=log_path / "openai.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=0,
    encoding="utf-8",
)
file_handler_ai.setLevel(logging.DEBUG)
file_handler_ai.setFormatter(file_formatter)

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[
        console_handler
    ],
)

logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.INFO)

tg_app_logger = logging.getLogger("telegram.ext")
tg_app_logger.setLevel(logging.DEBUG)
tg_app_logger.addHandler(file_handler_tg) # 挂上文件 handler
tg_app_logger.propagate = False # 不再往上传播到 root

sa_logger = logging.getLogger("sqlalchemy")
sa_logger.setLevel(logging.DEBUG)
sa_logger.addHandler(file_handler_sql)
sa_logger.propagate = False

aps_logger = logging.getLogger("apscheduler")
aps_logger.setLevel(logging.DEBUG)
aps_logger.addHandler(file_handler_tg)
aps_logger.propagate = False

tg_log = logging.getLogger("telegram")
tg_log.setLevel(logging.DEBUG)
tg_log.addHandler(file_handler_tg)
tg_log.addHandler(console_handler)
tg_log.propagate = False

cache_log = logging.getLogger("cache")
cache_log.setLevel(logging.DEBUG)
cache_log.addHandler(file_handler_cache)
cache_log.addHandler(console_handler)
cache_log.propagate = False

sql_log = logging.getLogger("sql")
sql_log.setLevel(logging.DEBUG)
sql_log.addHandler(file_handler_sql)
sql_log.addHandler(console_handler)
sql_log.propagate = False

ai_log = logging.getLogger("ai")
ai_log.setLevel(logging.DEBUG)
ai_log.addHandler(file_handler_ai)
ai_log.addHandler(console_handler)
ai_log.propagate = False
