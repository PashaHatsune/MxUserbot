import os
import shutil
import importlib
from pathlib import Path
from loguru import logger

from ...registry import active_modules as modules


class Loader:
    def __init__(
            self
    ):
        self.module_path = Path(__file__).resolve().parents[1] / 'extra'
        self.module = None
        self.uv_path = shutil.which(
            cmd="uv"
        )
        if self.uv_path is None:
            raise RuntimeError("uv не найден в PATH")
        

    async def register_all_modules(
            self
    ) -> None:

        modulefiles = [
            str(self.module_path / mod) 
            for mod in os.listdir(self.module_path) 
            if mod.endswith(".py") and not mod.startswith("_")
        ]

        await self._register_module(modulefiles)
    

    async def _register_module(self, module_paths):
            loaded = []
            for mod_path in module_paths:
                logger.info(f'Loading module: {mod_path}..')
                
                stem = Path(mod_path).stem
                module_name = f'src.userbot.modules.extra.{stem}'
                
                spec = importlib.util.spec_from_file_location(module_name, mod_path)
                
                if spec is None:
                    logger.error(f"Не удалось создать spec для {mod_path}")
                    continue

                res = await self.register_module(spec, module_name)
                loaded.append(res)
            
            return loaded


    async def register_module(
            self,
            spec,
            module_name
    ):
        async def _exec():
            while True:
                try: 
                    module = importlib.util.module_from_spec(spec)
                    if "." in module_name:
                        module.__package__ = module_name.rsplit('.', 1)[0]

                    spec.loader.exec_module(module)
                    
                    if not hasattr(module, 'MatrixModule'):
                        logger.error(f"В модуле {module_name} нет класса MatrixModule. Пропускаем")
                        return

                    cls = getattr(module, 'MatrixModule')
                    short_name = module_name.split('.')[-1]
                    instance = cls(short_name) 

                    if not hasattr(instance, 'enabled'):
                        instance.enabled = True
                    modules[short_name] = instance
                    
                    logger.success(f"Модуль {short_name} полностью готов")
                    return instance

                except Exception as e:
                    logger.error(f"Ошибка в модуле {module_name}: {e}")
                    return

        return await _exec()