import aiohttp
from pathlib import Path
from typing import Any

from mautrix.types import MessageEvent
from ...core import loader, utils


REPO_RAW_URL = "https://raw.githubusercontent.com/MxUserBot/mx-modules/main"


class Meta:
    name = "LoaderModule"
    _cls_doc = "Скачивает, управляет и перезагружает модули из удаленного репозитория."
    version = "1.0.2"
    tags = ["system"]
    dependencies = ["pathlib"]


@loader.tds
class LoaderModule(loader.Module):
    strings = {
        "no_url_or_id": "❌ Укажите URL или ID модуля из репозитория",
        "downloading": "⏳ Скачиваю модуль...",
        "fetching_repo": "⏳ Ищу модуль <code>{id}</code> в репозитории...",
        "repo_not_found": "❌ Модуль <code>{id}</code> не найден в репозитории.",
        "done": "✅ Модуль загружен: <code>{name}</code>",
        "error": "❌ Ошибка: <code>{err}</code>",
        
        "reloaded_header": "<b>♻️ Модули перезагружены:</b><br>",
        "module_item": "▫️ <code>{name}</code><br>",
        
        "no_name": "❌ Укажите системное имя модуля для выгрузки (без .py)",
        "not_found": "❌ Модуль <code>{name}</code> не найден среди активных",
        "unloaded": "✅ Модуль <code>{name}</code> успешно выгружен и удалён",

        "search_no_query": "❌ Укажите текст для поиска. Например: <code>msearch music</code>",
        "search_header": "<b>🔍 Результаты поиска «{query}»:</b><br><br>",
        "search_item": "📦 <b>{name}</b> (<code>{id}</code>) v{version}<br>📝 <i>{desc}</i><br>📥 Установка: <code>mdl {id}</code><br><br>",
        "search_empty": "❌ По запросу <code>{query}</code> ничего не найдено.",

        "repo_fetching_list": "⏳ Получаю список модулей...",
        "repo_list_empty": "❌ Репозиторий пуст или недоступен.",
        "repo_list_header": "<b>📦 Официальный репозиторий:</b><br><details><summary>Развернуть список ({count} шт.)</summary><br>",
        "repo_list_item": "▫️ <b>{id}</b> — <small><i>{desc}</i></small><br>"
    }

    @loader.command()
    async def mdl(self, mx: Any, event: MessageEvent):
        """<url/id> — скачивает модуль по ссылке или из репозитория"""
        parts = event.content.body.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else None
        
        if not args:
            return await utils.answer(mx, event.room_id, self.strings.get("no_url_or_id"), edit_id=event.event_id)
        
        arg = args.strip()
        is_url = arg.startswith("http://") or arg.startswith("https://")

        download_url = ""
        filename = ""

        try:
            async with aiohttp.ClientSession() as session:
                if not is_url:
                    await utils.answer(mx, event.room_id, self.strings.get("fetching_repo").format(id=arg), edit_id=event.event_id)
                    
                    async with session.get(f"{REPO_RAW_URL}/index.json") as resp:
                        if resp.status != 200:
                            raise Exception(f"Не удалось получить index.json (HTTP {resp.status})")
                        repo_data = await resp.json(content_type=None) 
                    
                    mod_info = next((m for m in repo_data.get("modules", []) if m.get("id") == arg), None)
                    
                    if not mod_info:
                        return await utils.answer(mx, event.room_id, self.strings.get("repo_not_found").format(id=arg), edit_id=event.event_id)

                    download_url = f"{REPO_RAW_URL}/modules/{mod_info['path']}"
                    filename = mod_info["path"]
                else:
                    download_url = arg
                    filename = Path(download_url).name
                    if not filename.endswith(".py"):
                        filename += ".py"

                await utils.answer(mx, event.room_id, self.strings.get("downloading"), edit_id=event.event_id)
                async with session.get(download_url, timeout=10) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    code = await resp.text()

            path = Path(self.loader.community_path) / filename
            path.write_text(code, encoding="utf-8")

            await self.loader.register_module(path, mx, is_core=False)

            await utils.answer(mx, event.room_id, self.strings.get("done").format(name=filename), edit_id=event.event_id)

        except Exception as e:
            await utils.answer(mx, event.room_id, self.strings.get("error").format(err=str(e)), edit_id=event.event_id)


    @loader.command()
    async def mrepo(self, mx: Any, event: MessageEvent):
        """Отображает полный список модулей из репозитория"""
        await utils.answer(mx, event.room_id, self.strings.get("repo_fetching_list"), edit_id=event.event_id)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{REPO_RAW_URL}/index.json") as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    repo_data = await resp.json(content_type=None)

            modules = repo_data.get("modules", [])
            if not modules:
                return await utils.answer(mx, event.room_id, self.strings.get("repo_list_empty"), edit_id=event.event_id)

            modules.sort(key=lambda x: x.get("id", ""))

            msg = self.strings.get("repo_list_header").format(count=len(modules))
            
            for mod in modules:
                msg += self.strings.get("repo_list_item").format(
                    id=mod.get("id", "unknown"),
                    desc=mod.get("description", "Без описания")
                )
            
            msg += "</details>"

            await utils.answer(mx, event.room_id, msg, edit_id=event.event_id)

        except Exception as e:
            await utils.answer(mx, event.room_id, self.strings.get("error").format(err=str(e)), edit_id=event.event_id)


    @loader.command()
    async def msearch(self, mx: Any, event: MessageEvent):
        """<запрос> — поиск модулей в официальном репозитории"""
        parts = event.content.body.split(maxsplit=1)
        query = parts[1].strip().lower() if len(parts) > 1 else None

        if not query:
            return await utils.answer(mx, event.room_id, self.strings.get("search_no_query"), edit_id=event.event_id)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{REPO_RAW_URL}/index.json") as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    repo_data = await resp.json(content_type=None)

            results = []
            for mod in repo_data.get("modules", []):
                search_text = f"{mod.get('id', '')} {mod.get('name', '')} {mod.get('description', '')} {' '.join(mod.get('tags', []))}".lower()
                
                if query in search_text:
                    results.append(mod)

            if not results:
                return await utils.answer(mx, event.room_id, self.strings.get("search_empty").format(query=query), edit_id=event.event_id)

            msg = self.strings.get("search_header").format(query=query)
            for mod in results:
                msg += self.strings.get("search_item").format(
                    name=mod.get("name"),
                    id=mod.get("id"),
                    version=mod.get("version"),
                    desc=mod.get("description")
                )

            await utils.answer(mx, event.room_id, msg, edit_id=event.event_id)

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
    async def unmd(self, mx: Any, event: MessageEvent):
        """<имя файла> — выгружает и безвозвратно удаляет комьюнити-модуль"""
        parts = event.content.body.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else None

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