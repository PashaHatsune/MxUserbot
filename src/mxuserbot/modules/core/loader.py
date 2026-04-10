import aiohttp
from pathlib import Path
from ...core import loader, utils

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "DLMod",
        "_cls_doc": "Скачивает и загружает модуль из удаленного репозитория",
        "no_url": "❌ URL не указан",
        "downloading": "⏳ Скачиваю модуль...",
        "done": "✅ Модуль загружен: <code>{name}</code>",
        "error": "❌ Ошибка: <code>{err}</code>"
    }

    @loader.command()
    async def mdl(self, mx, event):
        """!mdl <url> — скачивает и подгружает модуль"""
        args = utils.get_args_raw(event.content.body)
        
        if not args:
            return await mx.answer(self.strings.get("no_url"))
        
        url = args.strip()
        await mx.answer(self.strings.get("downloading"))

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

            await mx.answer(self.strings.get("done").format(name=filename))

        except Exception as e:
            await mx.answer(self.strings.get("error").format(err=str(e)))