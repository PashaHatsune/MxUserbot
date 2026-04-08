import aiohttp
import asyncio
from pathlib import Path
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "DLMod",
        "_cls_doc": "Скачивает и загружает модуль из удаленного репозитория",
        "no_url": "❌ URL не указан",
        "downloading": "⏳ Скачиваю модуль...",
        "done": "✅ Модуль загружен: {name}",
        "error": "❌ Ошибка: {err}"
    }

    @loader.command()
    async def mdl(self, mx, event):
        """!mdl <url> — скачивает и подгружает модуль"""
        text = getattr(event.content, "body", "")
        parts = text.split()
        if len(parts) < 2:
            return await mx.client.send_text(event.room_id, self.strings["no_url"])
        
        url = parts[1]
        await mx.client.send_text(event.room_id, self.strings["downloading"])

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    code = await resp.text()

            filename = Path(url).name
            path = Path(mx.all_modules.community_path) / filename
            path.write_text(code, encoding="utf-8")

            await mx.all_modules.register_module(path, mx)

            await mx.client.send_text(event.room_id, self.strings["done"].format(name=filename))

        except Exception as e:
            await mx.client.send_text(event.room_id, self.strings["error"].format(err=str(e)))