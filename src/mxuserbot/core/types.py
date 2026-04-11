import asyncio
import contextlib
import logging
import sys
from abc import ABC
from typing import Any, AsyncGenerator

import aiohttp
from loguru import logger
from ruamel.yaml.comments import CommentedMap

from mautrix.client import Client
from mautrix.client.state_store import MemoryStateStore as BaseMemoryStateStore
from mautrix.crypto.attachments import encrypt_attachment
from mautrix.crypto.store import MemoryCryptoStore as BaseMemoryCryptoStore
from mautrix.types import (
    CrossSigningUsage,
    EventID,
    EventType,
    Format,
    ImageInfo,
    MediaMessageEventContent,
    MessageType,
    RelatesTo,
    RoomID,
    TOFUSigningKey,
)
from mautrix.util.config import BaseFileConfig, RecursiveDict, ConfigUpdateHelper

from ...settings import config
from . import utils

class ModuleConfig:
    def __init__(self, getter_func, setter_func, **defaults):
        self._getter = getter_func
        self._setter = setter_func
        self._cache = defaults.copy()

    async def _load_from_db(self):
        for key in self._cache.keys():
            # Используем переданную безопасную функцию
            val = await self._getter(key, self._cache[key])
            self._cache[key] = val

    def __getitem__(self, key):
        return self._cache.get(key)

    def __setitem__(self, key, value):
        self._cache[key] = value
        # Используем переданную безопасную функцию
        asyncio.create_task(self._setter(key, value))

class Module(ABC):
    __origin__ = "<unknown>"
    __module_hash__ = "unknown"
    __source__ = ""

    config = {}
    strings = {}

    async def _internal_init(self, name, db, loader_or_dict, is_core: bool):
        self.name = name
        self._is_core = is_core
        self.name = name
        self.enabled = True
        self.logger = logger.bind(name=self.name)
        self._is_core = is_core
        
        if is_core:
            self._db = db
            self.loader = loader_or_dict 
            self.allmodules = loader_or_dict.active_modules 
        else:
            self._db = None
            self.loader = None
            self.allmodules = loader_or_dict # Это просто dict

        self._get = db.get
        self._set = db.set


        self.strings = getattr(self.__class__, "strings", {}).copy()
        self.friendly_name = self.strings.get("name") or self.config.get("name") or self.__class__.__name__

        defaults = getattr(self, "config", {})
        
        self.config = ModuleConfig(self._get, self._set, **defaults)
        await self.config._load_from_db()

        self._commands = {}
        for cmd_name, func in utils.get_commands(self.__class__).items():
            self._commands[cmd_name] = getattr(self, func.__name__)

    def _help(self):
        return self.strings.get("_cls_doc", "Описание отсутствует")


    @property
    def commands(self):
        return self._commands

    async def _get(self, key, default=None): 
        return await self._db.get(self.name, key, default)
        
    async def _set(self, key, value): 
        return await self._db.set(self.name, key, value)

    async def _matrix_start(self, mx): pass
    async def _matrix_message(self, mx, event): pass
    async def _matrix_member(self, mx, event): pass




    def _matrix_stop(self, mx): pass
    async def _matrix_poll(self, mx, pollcount): pass
    



class Config(BaseFileConfig):
    def __init__(self, path: str, base_path: str, db: Any = None) -> None:
        super().__init__(path, base_path)
        self.db = db
        self.owner = "core"
        self._default_values = {
            "matrix": {
                "base_url": config.matrix_config.base_url,
                "username": config.matrix_config.owner,
                "password": config.matrix_config.password.get_secret_value(),
                "device_id": "",
                "access_token": "",
                "log_room_id": "",
                "owner": config.matrix_config.owner
            },
            "logging": {"version": 1}
        }

        self._data = RecursiveDict(self._default_values, CommentedMap)

    def load_base(self) -> RecursiveDict:
        return RecursiveDict(self._default_values, CommentedMap)

    def load(self) -> None: pass
    def save(self) -> None: pass

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("matrix")
        helper.copy("logging")

    async def load_from_db(self) -> None:
        if not self.db: return
        async def fetch_recursive(data_dict: dict, prefix=""):
            for key, value in data_dict.items():
                full_key = f"{prefix}{key}"
                if isinstance(value, dict):
                    await fetch_recursive(value, f"{full_key}.")
                else:
                    db_value = await self.db.get(self.owner, full_key)
                    if db_value is not None:
                        self[full_key] = db_value
        await fetch_recursive(self._default_values)

    async def update_db_key(self, key: str, value: Any) -> None:
        self[key] = value
        if self.db:
            await self.db.set(self.owner, key, value)






class InterceptHandler(logging.Handler):
    """Перехватчик стандартных логов Python и перенаправление их в Loguru."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
            
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
            
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())



class MemoryCryptoStore(BaseMemoryCryptoStore):
    """Исправленное хранилище ключей."""
    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None, None]:
        yield

    async def put_cross_signing_key(self, user_id: str, usage: CrossSigningUsage, key: str) -> None:
        """Фикс ошибки AttributeError: can't set attribute."""
        try:
            current = self._cross_signing_keys[user_id][usage]
            self._cross_signing_keys[user_id][usage] = TOFUSigningKey(key=key, first=current.first)
        except KeyError:
            self._cross_signing_keys.setdefault(user_id, {})[usage] = TOFUSigningKey(key=key, first=key)

class CustomMemoryStateStore(BaseMemoryStateStore):
    async def find_shared_rooms(self, user_id: str) -> list[str]:
        shared = []
        for room_id, members in getattr(self, "members", {}).items():
            if user_id in members: shared.append(room_id)
        return shared

