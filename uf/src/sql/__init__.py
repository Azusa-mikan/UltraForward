import sys
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from pathlib import Path
from uf.src.config import config
from uf.src.log import sql_log

match config.database.type:
    case "sqlite":
        database_path = Path(__file__).parents[3] / "data"
        if not database_path.exists():
            database_path.mkdir(exist_ok=True)
        db_file = database_path / f"{config.database.database}.db"
        DATABASE_URL = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    case "mysql" | "mariadb":
        DATABASE_URL = f"mysql+asyncmy://{config.database.user}:{config.database.password}@{config.database.host}:{config.database.port}/{config.database.database}"
    case "postgresql":
        DATABASE_URL = f"postgresql+asyncpg://{config.database.user}:{config.database.password}@{config.database.host}:{config.database.port}/{config.database.database}"
    case _:
        raise ValueError(f"未知数据库类型: {config.database.type}")

try:
    match config.database.type:
        case "sqlite":
            engine = create_async_engine(
                DATABASE_URL,
                echo=False,
                pool_size=1,
                max_overflow=0,
                connect_args={"timeout": 30},
            )
        case "mysql" | "mariadb" | "postgresql":
            engine = create_async_engine(
                DATABASE_URL,
                echo=False,
                pool_size=10,
                max_overflow=20,
                pool_timeout=15,
                pool_recycle=600,
                pool_pre_ping=True,
            )
except ModuleNotFoundError as e:
    sql_log.critical(
        "未安装相应的数据库驱动:\n"
        "请根据数据库类型安装对应的驱动:\n\n"
        "SQLite: pip install aiosqlite\n"
        "MySQL: pip install asyncmy\n"
        "MariaDB: 与MySQL相同\n"
        "PostgreSQL: pip install asyncpg\n\n"
        f"根据配置文件，你应该安装 {e.name}"
    )
    if e.name == "asyncmy":
        sql_log.warning(
            "注意：如果你的 Python 版本大于或等于 3.13，安装 asyncmy 可能需要编译\n"
            "如果不接受编译，你可以选用其它数据库。"
        )
    sys.exit(1)
except Exception as e:
    sql_log.critical(f"数据库连接失败: {e}")
    raise

SessionLocal = async_sessionmaker(bind=engine, autoflush=True)

class Base(DeclarativeBase):
    pass

async def init_db():
    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.run_sync(Base.metadata.create_all)

async def healthy() -> tuple[bool, str]:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        return True, ""
    except Exception as e:
        return False, str(e)