import os
import shutil
import importlib
import importlib.util
from pathlib import Path
from loguru import logger
import inspect
import hashlib
import typing

from .types import Module
from . import utils 

def _calc_module_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()


_MODULE_NAME_BY_HASH: typing.Dict[str, str] = {}

from functools import wraps



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



class Loader:
    def __init__(self, db_wrapper):
        self.db = db_wrapper 
        self.active_modules: typing.Dict[str, object] = {}
        
        self.module_path = Path(__file__).resolve().parents[2] / 'userbot' / 'modules'
        self.uv_path = shutil.which(cmd="uv")

    async def register_all(self) -> None:
        print(self.module_path)
        """Загрузить все модули из папки extra"""
        if not os.path.exists(self.module_path):
            os.makedirs(self.module_path)

        modulefiles = [
            str(self.module_path / mod) 
            for mod in os.listdir(self.module_path) 
            if mod.endswith(".py") and not mod.startswith("_")
        ]
        
        for mod_path in modulefiles:
            logger.info(f'Loading: {mod_path}')
            stem = Path(mod_path).stem
            module_name = f'src.userbot.modules.{stem}'
            
            spec = importlib.util.spec_from_file_location(module_name, mod_path)
            if spec:
                await self.register_module(spec, module_name)

    def _apply_metadata(self, instance, spec):
        """Запись исходника и хэша"""
        try:
            with open(spec.origin, 'r', encoding='utf-8') as f:
                source = f.read()
            instance.__source__ = source
            instance.__module_hash__ = _calc_module_hash(source)
            instance.__origin__ = spec.origin
            _MODULE_NAME_BY_HASH[instance.__module_hash__] = instance.__class__.__name__
        except Exception:
            instance.__module_hash__ = "unknown"

    async def register_module(self, spec, module_name):
        """Регистрация одиночного модуля"""
        try: 
            module = importlib.util.module_from_spec(spec)
            if "." in module_name:
                module.__package__ = module_name.rsplit('.', 1)[0]

            spec.loader.exec_module(module)
            
            if not hasattr(module, 'MatrixModule'):
                return None

            cls = getattr(module, 'MatrixModule')
            short_name = module_name.split('.')[-1]
            
            try:
                instance = cls() 
            except TypeError:
                instance = cls(short_name)

            if hasattr(instance, '_internal_init'):
                await instance._internal_init(short_name, self.db, self)

            self._apply_metadata(instance, spec)
            
            self.active_modules[short_name] = instance
            
            logger.success(f"Модуль {short_name} загружен. Hash: {instance.__module_hash__[:8]}")
            return instance

        except Exception as e:
            logger.exception(f"Ошибка в модуле {module_name}: {e}")
            return None

