import os
import shutil
import importlib
import importlib.util
from pathlib import Path
from loguru import logger
import inspect
import hashlib
import typing

from ...registry import active_modules as modules
from .types import Module

def _calc_module_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()

_MODULE_NAME_BY_HASH: typing.Dict[str, str] = {}

class Loader:
    def __init__(self):
        self.module_path = Path(__file__).resolve().parents[1] / 'extra'
        self.uv_path = shutil.which(cmd="uv")
        if self.uv_path is None:
            raise RuntimeError("uv не найден в PATH")
        
    async def register_all_modules(self) -> None:
        modulefiles =[
            str(self.module_path / mod) 
            for mod in os.listdir(self.module_path) 
            if mod.endswith(".py") and not mod.startswith("_")
        ]
        await self._register_module(modulefiles)
    
    async def _register_module(self, module_paths):
        loaded =[]
        for mod_path in module_paths:
            logger.info(f'Loading module: {mod_path}..')
            stem = Path(mod_path).stem
            module_name = f'src.userbot.modules.extra.{stem}'
            
            spec = importlib.util.spec_from_file_location(module_name, mod_path)
            if spec is None:
                continue

            res = await self.register_module(spec, module_name)
            if res:
                loaded.append(res)
        return loaded

    def _apply_metadata(self, instance, spec):
        try:
            if hasattr(spec, "origin") and spec.origin and os.path.exists(spec.origin):
                with open(spec.origin, 'r', encoding='utf-8') as f:
                    source_code = f.read()
            else:
                source_code = inspect.getsource(instance.__class__)
            
            instance.__source__ = source_code
            instance.__module_hash__ = _calc_module_hash(source_code)
            instance.__origin__ = spec.origin if hasattr(spec, "origin") else "<unknown>"
            _MODULE_NAME_BY_HASH[instance.__module_hash__] = instance.__class__.__name__
        except Exception as e:
            instance.__source__ = ""
            instance.__module_hash__ = "unknown"
            instance.__origin__ = "<error>"

    async def register_module(self, spec, module_name):
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
                instance._internal_init(short_name)

            self._apply_metadata(instance, spec)
            modules[short_name] = instance
            
            logger.success(f"Модуль {short_name} полностью готов. Hash: {instance.__module_hash__[:8]}")
            return instance

        except Exception as e:
            logger.exception(f"Ошибка в модуле {module_name}: {e}")
            return None