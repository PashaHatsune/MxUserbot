from loguru import logger
import asyncio
from abc import ABC


from . import utils

class ModuleConfig:
    def __init__(self, db, module_name, **defaults):
        self._db = db
        self._module_name = module_name
        self._cache = defaults.copy()

    async def _load_from_db(self):
        for key in self._cache.keys():
            val = await self._db.get(self._module_name, key, self._cache[key])
            self._cache[key] = val

    def __getitem__(self, key):
        return self._cache.get(key)

    def __setitem__(self, key, value):
        self._cache[key] = value
        asyncio.create_task(self._db.set(self._module_name, key, value))


class Module(ABC):
    __origin__ = "<unknown>"
    __module_hash__ = "unknown"
    __source__ = ""

    config = {}
    strings = {}

    async def _internal_init(self, name, db, allmodules):
        self.name = name
        self.db = db
        self.allmodules = allmodules
        self.enabled = True
        self.logger = logger.bind(name=self.name)
        
        self.strings = getattr(self.__class__, "strings", {}).copy()

        self.friendly_name = self.strings.get("name") or self.config.get("name") or self.__class__.__name__

        defaults = getattr(self, "config", {})
        self.config = ModuleConfig(self.db, self.name, **defaults)
        await self.config._load_from_db()

        self._commands = {}
        for cmd_name, func in utils.get_commands(self.__class__).items():
            self._commands[cmd_name] = getattr(self, func.__name__)
    
    def _help(self):
        """Возвращает основную документацию модуля"""
        return self.strings.get("_cls_doc", "Описание отсутствует")

    @property
    def commands(self):
        return self._commands

    async def _get(self, key, default=None): 
        return await self.db.get(self.name, key, default)
        
    async def _set(self, key, value): 
        return await self.db.set(self.name, key, value)

    async def _matrix_start(self, mx): pass
    async def _matrix_message(self, mx, event): pass
    async def _matrix_member(self, mx, event): pass



    
    def _matrix_stop(self, mx): pass
    async def _matrix_poll(self, mx, pollcount): pass
    



