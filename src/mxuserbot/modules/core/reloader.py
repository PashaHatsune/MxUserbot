import sys
from typing import Any
from mautrix.types import MessageEvent
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "ReloadModule",
        "_cls_doc": "Модуль для горячей перезагрузки всех модулей с проверкой хэшей.",
        "reloaded_header": "<b>♻️ Модули перезагружены:</b>\n",
        "module_item": "▫️ <code>{name}</code>\n"
    }

    @loader.command()
    async def reload(self, mx: Any, event: MessageEvent):
        """Позволяет перезагружать модули"""
        old_info = {
            name: getattr(mod, "__module_hash__", "unknown")[:8] 
            for name, mod in mx.active_modules.items()
        }

        mx.stop()

        for stem in list(old_info.keys()):
            module_name = f'src.userbot.modules.{stem}'
            if module_name in sys.modules:
                del sys.modules[module_name]

        mx.all_modules.active_modules.clear()
        mx.active_modules.clear()

        await mx.all_modules.register_all(mx)
        
        mx.active_modules = mx.all_modules.active_modules

        msg = self.strings["reloaded_header"]
        for name in mx.active_modules.keys():
            msg += self.strings["module_item"].format(name=name)

        await mx.client.send_text(
            room_id=event.room_id, 
            html=msg
        )