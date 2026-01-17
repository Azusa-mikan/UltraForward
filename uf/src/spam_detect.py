from pathlib import Path
import asyncio
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, ValidationError
from aiolimiter import AsyncLimiter
from time import perf_counter

from uf.src.config import config
from uf.src.log import ai_log

detect_path = Path(__file__).resolve().parent / "assets" / "prohibited_words.txt"
prohibited_words: list[str] = detect_path.read_text(encoding="utf-8").splitlines()

global_prompt = (
    "You are a Telegram message moderation detector. "
    "\n\n"
    "Task: Given exactly ONE user message, decide whether it should be BLOCKED. "
    "IMPORTANT: The output field name is 'spam', but here it means 'should_block'. "
    "\n\n"
    "Set 'spam': true if the message contains ANY of the following: "
    "(1) spam/unsolicited promotion/ads; "
    "(2) abusive/offensive/profanity/insults; "
    "(3) harassment/hate/threats/scams/illegal content/explicit sexual content; "
    "(4) any clear violation of common community rules. "
    "Otherwise set 'spam': false. "
    "\n\n"
    "Consistency rule (MUST follow): "
    "If your reason indicates any abuse/offense/profanity/violation, then 'spam' MUST be true. "
    "If you are uncertain, choose 'spam': true (conservative). "
    "\n\n"
    "Return ONLY a valid JSON object (no markdown, no extra text), exactly in this schema: "
    "{\"spam\": <true|false>, \"reason\": \"<Chinese reason within 50 words>\"}"
    "\n\n"
    "Examples: "
    "Input: 你他妈在干嘛 "
    "Output: {\"spam\": true, \"reason\": \"包含明显脏话/辱骂，不文明用语，违反社区规则。\"} "
    "Input: 加我微信免费领资源 "
    "Output: {\"spam\": true, \"reason\": \"疑似引流推广/垃圾广告信息。\"} "
    "Input: 你好，请问怎么使用？ "
    "Output: {\"spam\": false, \"reason\": \"正常提问交流，未见违规。\"}"
)

class Spam(BaseModel):
    model_config = ConfigDict(
        extra='forbid'
    )

    spam: bool
    reason: str

class SpamDetector:
    def __init__(self) -> None:
        self.base_url: str = self._replace_base_url(config.openai.base_url)
        self.model: str = config.openai.model
        self.token: str = config.openai.token
        self.client = AsyncOpenAI(
            api_key=self.token,
            base_url=self.base_url,
        )
        self.limiter = AsyncLimiter(
            config.openai.rpm,
            config.openai.time_period,
        )

    def _replace_base_url(self, url: str) -> str:
        if url.endswith('/'):
            return url.rstrip('/')
        return url

    async def _detect_of_openai(self, text: str) -> str | None:
        start_wait = perf_counter()
        await self.limiter.acquire()
        waited = perf_counter() - start_wait
        if waited >= 0.1:
            ai_log.warning(f"AI 请求触发限流，已等待 {waited:.2f}s")
        else:
            ai_log.debug(f"AI 请求通过限流器（wait={waited:.2f}s）")
        if config.openai.json_mode:
            response_format = {"type": "json_object"}
        else:
            response_format = None
        coro = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": global_prompt,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            stream=False,
            temperature=0,
            response_format=response_format, # type: ignore
        )
        response = await asyncio.wait_for(coro, 40.0)
        msg = response.choices[0].message
        answer = msg.content
        reasoning = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
        ai_log.debug(f"AI思考内容：{reasoning!r}")
        ai_log.debug(f"AI输出内容：{answer!r}")
        return answer
    
    def _detect_of_words(self, text: str) -> Spam:
        word = next((w for w in prohibited_words if w in text), None)
        if word is not None:
            ai_log.debug(f"触发关键词: {word}")
            return Spam(spam=True, reason=f"触发关键词: {word}")
        return Spam(spam=False, reason="未触发任何关键词")
    
    async def check_spam(self, text: str) -> tuple[bool, str]:
        if not self.token or not self.base_url or not self.model:
            ai_log.warning("未正确设置AI相关设置，已回退到关键词判断")
            spam = self._detect_of_words(text)
            return spam.spam, spam.reason

        try:
            response = await self._detect_of_openai(text)
            spam = Spam.model_validate_json(response) # type: ignore
        except asyncio.TimeoutError:
            ai_log.error("AI调用超时，已回退到关键词判断")
            spam = self._detect_of_words(text)
        except OpenAIError as e:
            ai_log.error(f"AI调用错误，已回退到关键词判断：{e}")
            spam = self._detect_of_words(text)
        except (ValidationError, TypeError, ValueError) as e:
            ai_log.error(f"AI输出的json不合法，已回退到关键词判断：{e}")
            spam = self._detect_of_words(text)
        except Exception as e:
            ai_log.exception(f"其它错误：{e}")
            raise

        return spam.spam, spam.reason



