from typing import Any
from datetime import datetime
import asyncio
import time
from collections import deque
from pympler import asizeof
from hurry.filesize import size
from uf.src.log import cache_log

class DataCache:
    def __init__(self) -> None:
        self.user_locks: dict[int, asyncio.Lock] = {}
        self.user_data: dict[int, dict[str, Any]] = {}
        self.topic_data: dict[int, dict[str, Any]] = {}
        self.user_message_time_queues: dict[int, deque[float]] = {}
        self.startup_time: datetime = datetime.now()
    
    def get_user_lock(self, user_id: int) -> asyncio.Lock:
        """
        根据用户 ID 获取对应的 asyncio.Lock 实例。
        
        如果该用户尚未在 user_locks 字典中注册，则新建一个 Lock 并缓存；
        否则直接返回已存在的 Lock。
        
        Args:
            user_id (int): 用户唯一标识符。
        
        Returns:
            asyncio.Lock: 与该用户绑定的异步锁对象。
        """
        # 尝试从缓存中获取已存在的锁
        lock = self.user_locks.get(user_id)
        if lock is None:
            # 若不存在，则新建一个锁
            lock = asyncio.Lock()
            # 使用 setdefault 确保线程安全地写入缓存
            lock = self.user_locks.setdefault(user_id, lock)
            cache_log.debug(f"为 {user_id} 创建了新的异步锁")
        else:
            cache_log.debug(f"{user_id} 异步锁缓存被命中")
        return lock
    
    def _get_user_data(self, user_id: int) -> dict[str, Any]:
        """
        根据用户 ID 获取对应的缓存数据。
        
        如果该用户尚未在 user_data 字典中注册，则新建一个空字典并缓存；
        否则直接返回已存在的字典。
        
        Args:
            user_id (int): 用户唯一标识符。
        
        Returns:
             
            dict[str, Any]: 与该用户绑定的缓存数据字典。
        """
        data = self.user_data.get(user_id)
        if data is None:
            data = {}
            self.user_data[user_id] = data
            cache_log.debug(f"为 {user_id} 创建了缓存")
        return data

    def _get_user_message_time_queue(self, user_id: int) -> deque[float]:
        """获取指定用户的消息时间戳队列。

        队列元素是 time.monotonic() 返回的秒数（float），只用于计算时间差。
        """
        q = self.user_message_time_queues.get(user_id)
        if q is None:
            q = deque()
            self.user_message_time_queues[user_id] = q
        return q

    def flood_message(self, user_id: int, window: float = 4.0) -> int:
        """记录一次消息并返回该用户在窗口期内的消息数量。

        - 使用 time.monotonic()：不受系统时间回拨影响，适合做限流窗口。
        - 复杂度：均摊 O(1)。每条时间戳最多 append 一次、popleft 一次。

        Args:
            user_id: Telegram 用户 ID
            window: 滑动窗口秒数（例如 4.0 表示统计最近 4 秒）
        """
        if window <= 0:
            return 0

        now = time.monotonic()
        q = self._get_user_message_time_queue(user_id)
        q.append(now)

        # 清理窗口外的历史时间戳
        while q and (now - q[0]) > window:
            q.popleft()

        # 队列空了就移除该用户，避免字典无限增长
        if not q:
            self.user_message_time_queues.pop(user_id, None)

        return len(q)
    
    def _get_topic_data(self, topic_id: int) -> dict[str, Any]:
        """
        根据话题 ID 获取对应的缓存数据。
        
        如果该话题尚未在 topic_data 字典中注册，则新建一个空字典并缓存；
        否则直接返回已存在的字典。
        
        Args:
            topic_id (int): 话题唯一标识符。
        
        Returns:
             
            dict[str, Any]: 与该话题绑定的缓存数据字典。
        """
        data = self.topic_data.get(topic_id)
        if data is None:
            data = {}
            self.topic_data[topic_id] = data
            cache_log.debug(f"为 {topic_id} 创建了缓存")
        return data

    def get_flag(self, user_id: int, key: str, default: Any = None) -> Any:
        """
        获取用户缓存中的键对应的值。
        
        Args:
            user_id (int): 用户唯一标识符。
            key (str): 缓存键名。
            default (Any, optional): 如果键不存在时返回的默认值。默认值为 None。
        
        Returns:
            Any: 对应的值，若键不存在则返回默认值。
        """
        data = self._get_user_data(user_id)
        cache_log.debug(f"{user_id} 缓存被命中")
        cache_log.debug(f"为 {user_id} 获取的内容: {key}")
        return data.get(key, default)

    def set_flag(self, user_id: int, key: str, value: Any) -> None:
        """
        设置用户缓存中的键值对。
        
        Args:
            user_id (int): 用户唯一标识符。
            key (str): 缓存键名。
            value (Any): 对应的值。
        """
        data = self._get_user_data(user_id)
        data[key] = value
        cache_log.debug(f"{user_id} 缓存被更新")
        cache_log.debug(f"为 {user_id} 设置的内容: {key} = {value}")
    
    def get_topic(self, topic_id: int, key: str, default: Any = None) -> Any:
        """
        获取话题缓存中的键对应的值。
        
        Args:
            topic_id (int): 话题唯一标识符。
            key (str): 缓存键名。
            default (Any, optional): 如果键不存在时返回的默认值。默认值为 None。
        
        Returns:
            Any: 对应的值，若键不存在则返回默认值。
        """
        data = self._get_topic_data(topic_id)
        cache_log.debug(f"{topic_id} 缓存被命中")
        cache_log.debug(f"为 {topic_id} 获取的内容: {key}")
        return data.get(key, default)

    def set_topic(self, topic_id: int, key: str, value: Any) -> None:
        """
        设置话题缓存中的键值对。
        
        Args:
            topic_id (int): 话题唯一标识符。
            key (str): 缓存键名。
            value (Any): 对应的值。
        """
        data = self._get_topic_data(topic_id)
        data[key] = value
        cache_log.debug(f"{topic_id} 缓存被更新")
        cache_log.debug(f"为 {topic_id} 设置的内容: {key} = {value}")
    
    def get_cache_size(self) -> tuple[Any | str, Any | str, Any | str, Any | str]:
        """
        获取当前缓存占用的内存大小。
        
        Returns:
             
            tuple[Any | str, Any | str, Any | str, Any | str]: 顺序：用户锁、用户数据、话题数据、用户消息时间队列占用的内存大小。
             
            每个元素都是一个字符串，格式为 "{size}{unit}"，例如 "123B"。
        """
        return (
            size(asizeof.asizeof(self.user_locks)),
            size(asizeof.asizeof(self.user_data)),
            size(asizeof.asizeof(self.topic_data)),
            size(asizeof.asizeof(self.user_message_time_queues)),
        )

    def clear_user_all(self) -> None:
        self.user_data.clear()
        self.user_locks.clear()
        cache_log.debug(f"所有用户缓存被清除")
    
    def clear_topic_all(self) -> None:
        self.topic_data.clear()
        cache_log.debug(f"所有话题缓存被清除")
