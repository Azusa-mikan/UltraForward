from pydantic import BaseModel, ConfigDict, Field
from pathlib import Path
import yaml
import sys
from typing import Literal

class TGConfig(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True
    )

    token: str = Field(default="", description="Telegram Bot Token")
    topic_chat_id: int = Field(default=0, description="要转发到的话题群组ID（目标群组必须开启话题模式）")
    admin_id: int = Field(default=0, description="Bot的所有者")
    verify_ttl: int = Field(default=30, gt=0, description="验证码过期时间（默认30秒）")

class DatabaseConfig(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True
    )

    type: Literal['sqlite', 'mysql', 'mariadb', 'postgresql'] = Field(default="sqlite", description="数据库类型")
    host: str = Field(default="0.0.0.0", description="数据库主机地址")
    port: int = Field(default=3306, gt=0, description="数据库端口号")
    user: str = Field(default="root", description="数据库用户名")
    password: str = Field(default="password", description="数据库密码")
    database: str = Field(default="vrb", description="数据库名称")

class OpenAIConfig(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True
    )

    base_url: str = Field(default="https://api.siliconflow.cn/v1", description="API 提供商的基础 URL")
    model: str = Field(default="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", description="要使用的模型名称")
    token: str = Field(default="", description="API 提供商的 Token")
    json_mode: bool = Field(default=True, description="是否启用 JSON 模式（可加快响应速度）,如果API不支持可关闭，但可能会有问题")
    rpm: int = Field(default=5, gt=0, description="请求次数（相对于时间窗口）")
    time_period: int = Field(default=30, gt=0, description="时间窗口（秒）")

class BotConfig(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True
    )

    log_level: str = Field(default="INFO", description="控制台日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）")
    telegram: TGConfig = Field(default_factory=TGConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)

config_path = Path(__file__).parents[2] / "config" / "config.yaml"
if not config_path.parent.exists():
    config_path.parent.mkdir(parents=True, exist_ok=True)

if config_path.exists():
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}
        config = BotConfig(**config_data)
else:
    default_config = BotConfig()
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(default_config.model_dump(), f, default_flow_style=False, allow_unicode=True)
    print("已生成默认配置文件，请编辑后重新运行")
    sys.exit(0)