import aiohttp
import sys
from pathlib import Path
from typing import Any
from mautrix.types import MessageEvent
from ...core import loader, utils

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "DLMod",
        "_cls_doc": "Скачивает и загружает модуль из удаленного репозитория",
        "no_url": "❌ URL не указан",
        "downloading": "⏳ Скачиваю модуль...",
        "done": "✅ Модуль загружен: <code>{name}</code>",
        "reloaded_header": "<b>♻️ Модули перезагружены:</b>\n",
        "module_item": "▫️ <code>{name}</code>\n",
        "no_name": "❌ Укажите имя модуля для выгрузки",
        "not_found": "❌ Модуль {name} не найден среди активных",
        "unloaded": "✅ Модуль {name} успешно выгружен и удалён",
        "error": "❌ Ошибка: <code>{err}</code>"
    }

    @loader.command()
    async def mdl(self, mx: Any, event: MessageEvent):
        """!mdl <url> — скачивает и подгружает модуль"""
        args = utils.get_args_raw(event.content.body)
        
        if not args:
            return await utils.answer(mx, event.room_id, self.strings.get("no_url"), edit_id=event.event_id)
        
        url = args.strip()
        await utils.answer(mx, event.room_id, self.strings.get("downloading"), edit_id=event.event_id)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    code = await resp.text()

            filename = Path(url).name
            if not filename.endswith(".py"):
                filename += ".py"

            path = Path(self.loader.community_path) / filename
            path.write_text(code, encoding="utf-8")

            await self.loader.register_module(path, mx, is_core=False)

            await utils.answer(mx, event.room_id, self.strings.get("done").format(name=filename), edit_id=event.event_id)

        except Exception as e:
            await utils.answer(mx, event.room_id, self.strings.get("error").format(err=str(e)), edit_id=event.event_id)

    @loader.command()
    async def reload(self, mx: Any, event: MessageEvent):
        """Перезагрузка всех модулей"""
        active_names = list(mx.active_modules.keys())

        for name in active_names:
            try:
                await self.loader.unload_module(name, mx)
            except Exception:
                continue

        await self.loader.register_all(mx)

        msg = self.strings.get("reloaded_header")
        for name in mx.active_modules.keys():
            msg += self.strings.get("module_item").format(name=name)

        await utils.answer(mx, event.room_id, msg, edit_id=event.event_id)

    @loader.command()
    async def unlmd(self, mx: Any, event: MessageEvent):
        """!unlmd <имя модуля> — выгружает и удаляет модуль"""
        args = utils.get_args_raw(event.content.body)
        if not args:
            return await utils.answer(mx, event.room_id, self.strings.get("no_name"), edit_id=event.event_id)
        
        name = args.strip()

        if name not in mx.active_modules:
            return await utils.answer(mx, event.room_id, self.strings.get("not_found").format(name=name), edit_id=event.event_id)
        
        try:
            await self.loader.unload_module(name, mx)

            path = Path(self.loader.community_path) / f"{name}.py"
            if path.exists():
                path.unlink()

            await utils.answer(mx, event.room_id, self.strings.get("unloaded").format(name=name), edit_id=event.event_id)

        except Exception as e:
            await utils.answer(mx, event.room_id, self.strings.get("error").format(err=str(e)), edit_id=event.event_id)