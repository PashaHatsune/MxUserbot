import os
import typing
import shutil
import inspect
import hashlib
import asyncio
import importlib.util
from functools import wraps
from pathlib import Path
from loguru import logger

from . import utils
from .types import Module 
_MODULE_NAME_BY_HASH: typing.Dict[str, str] = {}


def _calc_module_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()


def command(name=None):
    def decorator(func):
        func.is_command = True
        func.command_name = (name or func.__name__).lower()
        return func
    return decorator


def tds(cls):
    """Decorator that makes triple-quote docstrings translatable"""
    if not hasattr(cls, 'strings'):
        cls.strings = {}

    @wraps(cls._internal_init)
    async def _internal_init(self, *args, **kwargs):
        def proccess_decorators(mark: str, obj: str):
            nonlocal self
            for attr in dir(func_):
                if (
                    attr.endswith("_doc")
                    and len(attr) == 6
                    and isinstance(getattr(func_, attr), str)
                ):
                    var = f"strings_{attr.split('_')[0]}"
                    if not hasattr(self, var):
                        setattr(self, var, {})

                    getattr(self, var).setdefault(f"{mark}{obj}", getattr(func_, attr))

        for command_, func_ in utils.get_commands(cls).items():
            proccess_decorators("_cmd_doc_", command_)
            try:
                func_.__doc__ = self.strings[f"_cmd_doc_{command_}"]
            except AttributeError:
                func_.__func__.__doc__ = self.strings[f"_cmd_doc_{command_}"]

        # self.__doc__ = self.strings.get("_cls_doc", self.__doc__)
        self.__class__.__doc__ = self.strings.get("_cls_doc", self.__class__.__doc__)

        return await self._internal_init._old_(self, *args, **kwargs)

    _internal_init._old_ = cls._internal_init
    cls._internal_init = _internal_init

    for command_, func in utils.get_commands(cls).items():
        cmd_doc = func.__doc__
        if cmd_doc:
            cls.strings.setdefault(f"_cmd_doc_{command_}", inspect.cleandoc(cmd_doc))

    cls_doc = cls.__dict__.get('__doc__') # Обходим наследование от ABC
    if cls_doc:
        cls.strings.setdefault("_cls_doc", inspect.cleandoc(cls_doc))

    def _require(key: str, error_msg: str):
        """Проверяет наличие и непустоту ключа в словаре strings"""
        if not str(cls.strings.get(key, "")).strip():
            raise ValueError(f"❌ {error_msg}")

    _require("name", f"Модуль '{cls.__name__}' ОБЯЗАН иметь ключ 'name' в strings!")
    _require("_cls_doc", f"Модуль '{cls.__name__}' ОБЯЗАН иметь docstring или ключ '_cls_doc' в strings!")

    for cmd_name in utils.get_commands(cls).keys():
        _require(f"_cmd_doc_{cmd_name}", f"Команда '!{cmd_name}' ОБЯЗАНА иметь docstring!")

    return cls


import sys
class Loader:
    def __init__(self, db_wrapper):
        self.db = db_wrapper 
        self.active_modules: typing.Dict[str, object] = {}
        self.module_path = Path(__file__).resolve().parents[2] / 'mxuserbot' / 'modules'
        self.core_path = self.module_path / "core"
        self.community_path = self.module_path / "community"

        self._background_tasks: typing.Set[asyncio.Task] = set()


    async def register_all(self, bot) -> None:
        """Сканирует core и community папки с приоритетом core"""
        for p in [self.core_path, self.community_path]:
            p.mkdir(parents=True, exist_ok=True)

        community_files = [f for f in self.community_path.iterdir() if f.suffix == ".py" and not f.name.startswith("_")]
        core_files = [f for f in self.core_path.iterdir() if f.suffix == ".py" and not f.name.startswith("_")]

        for path in community_files:
            await self.register_module(path, bot, is_core=False)

        for path in core_files:
            await self.register_module(path, bot, is_core=True)

        logger.info(f"Загружено модулей: {len(self.active_modules)} (Core приоритет применен).")


    async def register_module(self, path: Path, bot, is_core: bool = False):
        """Импорт модуля с учетом вложенности (core/community)"""
        subfolder = "core" if is_core else "community"
        module_name = f"src.mxuserbot.modules.{subfolder}.{path.stem}"
        
        try:
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            if not spec or not spec.loader:
                return

            module = importlib.util.module_from_spec(spec)
            module.__package__ = f"src.mxuserbot.modules.{subfolder}"
            
            spec.loader.exec_module(module)

            if not hasattr(module, 'MatrixModule'):
                return

            cls = getattr(module, 'MatrixModule')
            short_name = path.stem
            
            instance = cls()
            instance._is_ready = False
            instance._is_core = is_core

            if hasattr(instance, '_internal_init'):
                await instance._internal_init(short_name, self.db, self)

            self._apply_metadata(instance, spec)
            
            self.active_modules[short_name] = instance

            startup_task = asyncio.create_task(self._finalize_module_startup(instance, bot, short_name))
            self._background_tasks.add(startup_task)
            startup_task.add_done_callback(self._background_tasks.discard)

            type_str = "CORE" if is_core else "COMM"
            logger.debug(f"[{type_str}] Импортирован модуль: {short_name}")

        except Exception:
            logger.exception(f"Ошибка при импорте модуля {path.name}")


    async def unload_module(self, name: str, bot) -> bool:
        if name not in self.active_modules:
            logger.warning(f"Модуль {name} не найден среди активных.")
            return False

        instance = self.active_modules[name]

        try:
            if hasattr(instance, "_matrix_stop"):
                if inspect.iscoroutinefunction(instance._matrix_stop):
                    await instance._matrix_stop(bot)
                else:
                    instance._matrix_stop(bot)
        except Exception:
            logger.exception(f"Ошибка при вызове _matrix_stop у модуля {name}")

        module_name_to_del = None
        for mod_name in list(sys.modules.keys()):
            if mod_name.endswith(f".{name}") and "src.userbot.modules" in mod_name:
                module_name_to_del = mod_name
                break
        
        if module_name_to_del:
            del sys.modules[module_name_to_del]

        del self.active_modules[name]
        logger.success(f"Модуль {name} успешно выгружен.")
        return True



    async def _finalize_module_startup(self, instance, bot, name):
        """Фоновый метод: загрузка настроек и запуск _matrix_start"""
        try:
            # Загрузка конфига из БД
            if hasattr(instance, "set_settings"):
                saved_settings = await self.db.get(name, "__config__")
                if saved_settings:
                    instance.set_settings(saved_settings)

            if getattr(instance, "enabled", True) and hasattr(instance, "_matrix_start"):
                await instance._matrix_start(bot)
            
            instance._is_ready = True
            
            logger.success(f"Модуль {name} успешно запущен в фоне.")
        except Exception:
            logger.exception(f"Ошибка при запуске модуля {name}")


    def _apply_metadata(self, instance, spec):
        """Запись метаданных (исходник, хэш)"""
        try:
            with open(spec.origin, 'r', encoding='utf-8') as f:
                source = f.read()
            instance.__source__ = source
            instance.__module_hash__ = _calc_module_hash(source)
            instance.__origin__ = spec.origin
            _MODULE_NAME_BY_HASH[instance.__module_hash__] = instance.__class__.__name__
        except Exception:
            instance.__module_hash__ = "unknown"