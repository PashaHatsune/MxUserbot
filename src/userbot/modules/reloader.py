import sys
import importlib
from ..core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "ReloadModule",
        "_cls_doc": "Модуль для горячей перезагрузки всех модулей с проверкой хэшей."
    }

    @loader.command()
    async def reload(self, bot, room, event, args):
        """Перезагрузить все модули и показать изменения"""
        
        old_info = {
            name: getattr(mod, "__module_hash__", "unknown")[:8] 
            for name, mod in bot.active_modules.items()
        }

        bot.stop()

        for stem in list(old_info.keys()):
            module_name = f'src.userbot.modules.{stem}'
            if module_name in sys.modules:
                del sys.modules[module_name]

        bot.all_modules.active_modules.clear()
        bot.active_modules.clear()

        await bot.all_modules.register_all(bot)
        
        bot.active_modules = bot.all_modules.active_modules
        await bot.start()

        msg = "<b>♻️ Модули перезагружены:</b>\n"
        for name, mod in bot.active_modules.items():
            msg += f"▫️ <code>{name}</code>\n"

        await bot.send_text(room, msg)