# UltraForward

UltraForward 是一个功能强大的 Telegram PM Bot。

专为拥有「话题（Topics）」功能的群组设计。

它不仅能实现「一用户一话题」的私聊转发，还内置了验证码验证系统和基于 AI + 关键词的垃圾消息检测功能，并支持多种数据库后端。

## 参考实现

- [BetterForward](https://github.com/SideCloudGroup/BetterForward)：
  拥有相同基础功能，但额外功能不同。
- [ModularBot](https://t.me/ModularBot)：
  最基础的一用户一话题的 PM Bot。

## ✨ 主要功能

- **一用户一话题转发**
  - 用户向 Bot 私聊发送消息后，Bot 会在目标群组中为该用户创建独立话题。
  - 后续该用户的所有消息都会自动转发到对应的话题中，方便做工单/客服。

- **双向交流**
  - 管理员在群组话题中回复消息，Bot 会自动把回复转发回该用户的私聊。
  - 完整保留消息 ID 映射，支持后续撤回等操作。

- **视觉验证码验证（zzyCaptcha 改良版）**
  - 用户使用 `/start` 开始验证，Bot 会发送一个动图验证码。
  - 用户在私聊中输入验证码内容（不区分大小写），验证通过后才允许继续发送消息。
  - 验证支持重试次数限制，错误次数过多会自动封禁该用户。

- **AI 垃圾消息检测**
  - 使用 OpenAI 兼容接口（默认配置为 SiliconFlow + DeepSeek 模型）对文本消息进行垃圾检测。
  - 如未正确配置 AI 接口，则自动退回到本地关键词检测（使用 `uf/src/assets/prohibited_words.txt`）。
  - 支持限流（RPM + 时间窗口设置），出现异常会自动退回关键词检测。

- **多数据库支持**
  - 默认使用 SQLite，自动在项目根目录创建 `data/` 目录与数据库文件。
  - 同时支持 MySQL / MariaDB / PostgreSQL，通过配置切换。
  - 所有数据库操作使用 SQLAlchemy + 异步引擎。

- **用户 & 消息管理**
  - 记录私聊消息与话题消息的双向映射，支持撤回、统计等操作。
  - 支持封禁/解封用户，封禁后会阻止其继续使用 Bot。

- **定时任务**
  - 每天定时清理缓存（用户/话题缓存）。
  - 每天定时清理数据库中超过一定时间的消息记录。

- **日志系统**
  - 控制台彩色日志，等级可通过配置调整。
  - 同时输出到文件：
    - `logs/bot.log`：主业务日志。
    - `logs/sql.log`：数据库相关日志。
    - `logs/cache.log`：缓存相关日志。
    - `logs/openai.log`：OpenAI相关日志。

## 🛠️ 环境要求

- **Python**: >= 3.11
- **数据库**（任一即可）：
  - SQLite（默认，无需额外安装）
  - MySQL / MariaDB（可选，需要安装 `asyncmy`）
  - PostgreSQL（可选，需要安装 `asyncpg`）
  - 以上数据库对应的异步驱动均已在 Docker 镜像中安装。

## 📡 Telegram 群组准备

在正式启动 Bot 之前，请确保完成以下准备：

- 创建一个 Telegram 超级群（Supergroup）。
- 在群设置中开启：
  - 「话题 / Topics」功能。（如果群绑定了 频道 / Chanel，需要解绑才能开启）
- 将 Bot 拉入该群，并赋予以下权限（推荐直接设为管理员）：
  - 读取所有消息（关闭 Bot 隐私模式 / 允许读取全部消息）。
  - 管理消息（删除消息）。
  - 管理话题（Manage Topics）。
- 将该群的 ID 配置到 `config.yaml` 中的 `telegram.topic_chat_id`。

Bot 启动后会执行自检：

- 检查 `topic_chat_id` 对应的群是否为超级群。
- 检查是否开启话题功能。
- 检查 Bot 在群中是否为管理员、是否有管理话题权限。
- 尝试创建用于存放 Spam 消息的专用话题。

如自检失败，Bot 会在群内发送提示消息并写入日志。

## 🚀 启动机器人

```bash
# 克隆仓库并进入目录
git clone https://github.com/Azusa-mikan/UltraForward.git ultraforward && cd ultraforward

# 构建本地镜像
docker-compose build

# 首次运行生成默认配置
docker run --rm -v ./config:/app/config ultraforward:dev

# 编辑配置文件
nano ./config/config.yaml

# （可选）自定义 docker-compose.yaml
nano docker-compose.yaml

# 启动机器人
docker-compose up -d
```

## ⚙️ 配置说明

### 1. Telegram 相关配置

```yaml
telegram:
  token: ""          # 必填，Bot Token（从 @BotFather 获取）
  topic_chat_id: 0   # 必填，目标群组 ID（必须是开启话题功能的超级群）
  admin_id: 0        # 必填，Bot 所有者的 Telegram 用户 ID
  verify_ttl: 30     # 可选，验证码有效期（秒），默认 30
```

- `topic_chat_id`
  - 必须是一个 **超级群（supergroup）**。
  - 必须**开启话题模式（Topics）**。
- `admin_id`
  - 超级管理员，用于接收错误提示、告警等。

### 2. 数据库配置

```yaml
database:
  type: "sqlite"        # 可选：sqlite / mysql / mariadb / postgresql
  host: "0.0.0.0"       # 非 sqlite 时生效
  port: 3306            # 非 sqlite 时生效
  user: "root"          # 非 sqlite 时生效
  password: "password"  # 非 sqlite 时生效
  database: "vrb"       # 数据库名称（sqlite 时为 data/vrb.db）
```

- 当 `type: sqlite` 时：
  - 会在项目根目录下自动创建 `data/` 目录。
  - 数据库文件为 `data/<database>.db`（默认 `data/vrb.db`）。
- 当使用 MySQL/MariaDB/PostgreSQL 时：
  - 请确保安装了对应驱动：
    - SQLite: `aiosqlite`
    - MySQL/MariaDB: `asyncmy`
    - PostgreSQL: `asyncpg`
  - 以上驱动均已在 Docker 镜像中安装，无需额外配置。
  - 否则程序会在启动时输出错误并退出。

### 3. OpenAI / DeepSeek 垃圾检测配置

```yaml
openai:
  base_url: "https://api.siliconflow.cn/v1"        # API 基础 URL
  model: "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"   # 模型名称
  token: ""                                        # API Token（必填，否则退回关键词模式）
  json_mode: true                                  # 是否启用 JSON 模式（推荐开启）
  rpm: 5                                           # 每个时间窗口内最大请求数
  time_period: 30                                  # 限流时间窗口（秒）
```

- 当 `token` 未配置或为空，或 `base_url` / `model` 无效时：
  - 会自动退回到本地关键词检测。
- 关键词列表来源：`uf/src/assets/prohibited_words.txt`。
- 请求超时、响应 JSON 不合法、OpenAI SDK 抛错时，也会自动退回关键词检测。

### 4. 日志配置

```yaml
log_level: "INFO"  # 可选：DEBUG / INFO / WARNING / ERROR / CRITICAL
```

- 控制台日志等级由 `log_level` 控制。
- 文件日志固定输出到 `logs` 目录

## 📡 基本使用流程

### 1. 用户侧

- 用户向 Bot 发送 `/start`：
  - Bot 发送验证码 GIF 动图。
  - 用户输入验证码内容（不区分大小写），验证通过后才允许继续发送消息。
- 通过验证后：
  - 用户发送的每条消息都会被转发到你配置的目标群组中。
  - 每个用户对应一个单独话题，方便区分会话。

### 2. 管理员侧（在目标群组中）

- 每个用户拥有一个专属话题。
- 管理员在话题中回复消息：
  - Bot 会把回复转发回该用户的私聊。
- 如果消息被判定为垃圾（Spam）：
  - 会被转发到专门的「Spam 消息话题」中，并附带判定理由。
  - 相关消息记录会被存入数据库，后续由定时任务清理。

## 🔧 内置命令说明

- `/start`
  - 开始验证流程。
  - 通过验证后即可正常与 Bot 对话。

- `/help`
  - 显示帮助信息和命令说明。

- `/d`
  - 撤回一条消息。
  - 使用方式：在**私聊或话题中**，回复一条由 Bot 转发/发送的消息，然后发送 `/d`。
  - Bot 会尝试撤回私聊和话题中的对应消息。

- `/ban`
  - 封禁用户（仅管理员可用）。
  - 在对应用户的话题中执行；话题对应的用户将被加入封禁列表，后续消息会被阻止。

- `/unban`
  - 解封用户（仅管理员可用）。
  - 同样需要在对应用户的话题中执行。

- `/info`
  - 获取用户信息 / 消息细节 / Bot 信息（仅管理员可用）。

- `/verify`
  - 手动触发验证码验证（仅管理员可用）。
  - 可用于强制要求某个用户重新完成验证码验证。

其他行为：

- 发送验证码文本（在私聊中）：
  - 用于通过视觉验证码，驱动「验证 → 建立话题 → 正常通信」的流程。

## 🧹 定时任务与数据维护

- 每天 00:00：
  - 清理缓存（用户缓存、话题缓存）。
  - 清理数据库中早于一定时间的消息记录（默认 2 天）。

这些任务通过 `python-telegram-bot` 的 `JobQueue` 实现，无需额外配置。

## 📝 许可证

本项目采用 **GNU General Public License v3.0 (GPL-3.0)** 许可证。

### 第三方组件说明

本项目的部分代码（`uf/src/verify.py`）改编自 [zzyCaptcha](https://github.com/TianmuTNT/zzyCaptcha)，遵循 Apache License 2.0 协议。详细信息请参阅 `THIRD_PARTY_LICENSES/LICENSE.txt`。
