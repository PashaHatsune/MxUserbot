from pathlib import Path
from typing import Any
import json
import asyncio

from mautrix.types import MessageEvent, EncryptedEvent, MessageType
from mautrix.crypto.attachments import decrypt_attachment
from ...core import loader, utils


DEFAULT_REPO_URL = "https://raw.githubusercontent.com/MxUserBot/mx-modules/main"


class Meta:
    name = "LoaderModule"
    _cls_doc = "Module downloader and manager with multi-repository support."
    version = "1.7.0"
    tags = ["system"]


@loader.tds
class LoaderModule(loader.Module):
    config = {
        "repo_url": loader.ConfigValue(DEFAULT_REPO_URL, "Main system repository URL"),
        "repo_warn_ok": loader.ConfigValue(False, "User accepted third-party repo warning"),
        "dev_warn_ok": loader.ConfigValue(False, "User accepted dev/file installation warning")
    }

    strings = {
        "no_url_or_reply": "❌ | <b>Provide a Module ID, User/Module shortcut, or use <code>.mdl dev [url]</code>.</b>",
        "downloading": "⏳ | <b>Downloading...</b>",
        "fetching": "⏳ | <b>Searching for <code>{id}</code>...</b>",
        "repo_not_found": "❌ | <b>Module <code>{id}</code> not found in any repository.</b>",
        "done": "✅ | <b>Module loaded: <code>{name}</code></b>",
        "error": "❌ | <b>Error: <code>{err}</code></b>",
        "reloading": "⏳ | <b>Reloading all modules...</b>",
        "reloaded_header": "<b>♻️ | Modules reloaded:</b><br>",
        "module_item": "▫️ | <b><code>{name}</code></b><br>",
        "no_name": "❌ | <b>Provide module name (without .py).</b>",
        "not_found": "❌ | <b>Module <code>{name}</code> not found.</b>",
        "unloaded": "✅ | <b>Module <code>{name}</code> unloaded and deleted.</b>",
        "search_no_query": "❌ | <b>Provide search query.</b>",
        "search_header_system": "<b>🌐 | Found in System Repository:</b><br>",
        "search_header_community": "<br><b>👥 | Found in Community ({url}):</b><br>",
        "search_item": "📦 | <b>{name}</b> (<code>{id}</code>) v<b>{version}</b><br>📝 | <i>{desc}</i><br>📥 | <b><code>.mdl {cmd_id}</code></b><br>",
        "search_empty": "❌ | <b>No results found for <code>{query}</code>.</b>",
        "repo_added": "✅ | <b>Repository added: <code>{url}</code></b>",
        "repo_removed": "✅ | <b>Repository removed.</b>",
        "repo_invalid": "❌ | <b>Invalid repository or missing index.json.</b>",
        "file_not_py": "❌ | <b>File must be <code>.py</code></b>",
        "reply_decrypt_err": "❌ | <b>Failed to decrypt file message.</b>",
        "error_url": "❌ | <b>Provide repository URL.</b>",
        "dev_usage": "❌ | <b>Direct links and files require <code>dev</code> prefix.</b><br>Example: <code>.mdl dev https://...</code>",
        "invalid_module": "❌ | <b>Module structure is invalid (Missing Meta or Module class).</b>",
        "security_repo": "⚠️ | <b>SECURITY WARNING</b><br><b>You are adding a third-party repository. Modules from unknown sources can steal your session keys.</b><br><i>Wait 5 seconds to proceed...</i>",
        "security_module": "⚠️ | <b>SECURITY WARNING</b><br><b>Installing module from a community source. This action may be unsafe.</b><br><i>Wait 5 seconds to proceed...</i>",
        "security_dev": "⚠️ | <b>SECURITY WARNING</b><br><b>You are installing a module from a file or direct link. This is for development purposes only.</b><br><i>Wait 10 seconds to proceed...</i>"
    }

    def _convert_repo_url(self, url: str) -> str:
        url = url.strip().rstrip("/")
        if "github.com" in url and "raw.githubusercontent.com" not in url:
            url = url.replace("github.com", "raw.githubusercontent.com")
            if "/tree/" in url:
                url = url.replace("/tree/", "/")
            else:
                url += "/main"
        return url

    def _get_prefix_from_url(self, url: str) -> str:
        parts = url.split("/")
        if "raw.githubusercontent.com" in url:
            return parts[3]
        return "community"

    async def _get_community_repos(self):
        raw = await self._db.get("core", "community_repos")
        if not raw: return []
        if isinstance(raw, list): return raw
        try: return json.loads(raw)
        except: return []

    @loader.command()
    async def addrepo(self, mx, event: MessageEvent):
        """<url> — Add a community repository"""
        args = await utils.get_args(mx, event)
        if not args: return await utils.answer(mx, self.strings.get("error_url"))
        
        url = self._convert_repo_url(args[0])
        try:
            test = await utils.request(f"{url}/index.json", return_type="json")
            if not test or "modules" not in test: raise Exception()
        except:
            return await utils.answer(mx, self.strings.get("repo_invalid"))

        if not self.config.get("repo_warn_ok"):
            await utils.answer(mx, self.strings.get("security_repo"))
            await asyncio.sleep(5)
            self.config.set("repo_warn_ok", True)

        repos = await self._get_community_repos()
        if url not in repos:
            repos.append(url)
            await self._db.set("core", "community_repos", json.dumps(repos))
        
        await utils.answer(mx, self.strings.get("repo_added").format(url=url))

    @loader.command()
    async def delrepo(self, mx, event: MessageEvent):
        """<url> — Remove a community repository"""
        args = await utils.get_args(mx, event)
        if not args: return await utils.answer(mx, self.strings.get("error_url"))
        
        url = self._convert_repo_url(args[0])
        repos = await self._get_community_repos()
        if url in repos:
            repos.remove(url)
            await self._db.set("core", "community_repos", json.dumps(repos))
            await utils.answer(mx, self.strings.get("repo_removed"))
        else:
            await utils.answer(mx, self.strings.get("error_url"))

    @loader.command()
    async def mdl(self, mx, event: MessageEvent):
        """<url/id/user/module/reply> — Install module"""
        args = await utils.get_args(mx, event)
        reply_to = event.content.relates_to.in_reply_to if event.content.relates_to else None
        
        is_dev = False
        if args and args[0].lower() == "dev":
            is_dev = True
            args = args[1:]

        if reply_to and reply_to.event_id:
            if not is_dev:
                return await utils.answer(mx, self.strings.get("dev_usage"))

            if not self.config.get("dev_warn_ok"):
                await utils.answer(mx, self.strings.get("security_dev"))
                await asyncio.sleep(10)
                self.config.set("dev_warn_ok", True)

            replied_event = await mx.client.get_event(event.room_id, reply_to.event_id)
            if isinstance(replied_event, EncryptedEvent):
                try:
                    decrypted = await mx.client.crypto.decrypt_megolm_event(replied_event)
                    content = decrypted.content
                except: return await utils.answer(mx, self.strings.get("reply_decrypt_err"))
            else: content = replied_event.content

            if content.msgtype == MessageType.FILE:
                filename = content.body
                if not filename.endswith(".py"): return await utils.answer(mx, self.strings.get("file_not_py"))
                await utils.answer(mx, self.strings.get("downloading"))
                try:
                    if content.file:
                        ciphertext = await mx.client.download_media(content.file.url)
                        code_bytes = decrypt_attachment(ciphertext, content.file.key.key, content.file.hashes.get("sha256"), content.file.iv)
                    else: code_bytes = await mx.client.download_media(content.url)
                    
                    code = code_bytes.decode("utf-8")
                    path = Path(self.loader.community_path) / filename
                    path.write_text(code, encoding="utf-8")
                    
                    await self.loader.register_module(path, mx, is_core=False)
                    
                    if path.stem in mx.active_modules:
                        return await utils.answer(mx, self.strings.get("done").format(name=filename))
                    else:
                        if path.exists(): path.unlink()
                        return await utils.answer(mx, self.strings.get("invalid_module"))
                except Exception as e: return await utils.answer(mx, self.strings.get("error").format(err=str(e)))

        if not args: return await utils.answer(mx, self.strings.get("no_url_or_reply"))

        target = args[0]
        url, filename = None, None
        from_community = False
        needs_dev_warning = False

        if target.startswith("http"):
            if not is_dev:
                return await utils.answer(mx, self.strings.get("dev_usage"))
            
            url = target
            filename = Path(target).name if target.endswith(".py") else target.split("/")[-1] + ".py"
            from_community = True
            needs_dev_warning = True
        
        elif "/" in target:
            user_prefix, mod_id = target.split("/", 1)
            repos = await self._get_community_repos()
            for r_url in repos:
                if user_prefix.lower() in r_url.lower():
                    try:
                        data = await utils.request(f"{r_url}/index.json", return_type="json")
                        mod = next((m for m in data.get("modules", []) if m.get("id") == mod_id), None)
                        if mod:
                            url = f"{r_url}/modules/{mod['path']}"
                            filename = mod['path']
                            from_community = True
                            break
                    except: continue
        
        else:
            await utils.answer(mx, self.strings.get("fetching").format(id=target))
            system_repo = self.config.get("repo_url")
            try:
                data = await utils.request(f"{system_repo}/index.json", return_type="json")
                mod = next((m for m in data.get("modules", []) if m.get("id") == target), None)
                if mod:
                    url = f"{system_repo}/modules/{mod['path']}"
                    filename = mod['path']
            except: pass

        if not url: return await utils.answer(mx, self.strings.get("repo_not_found").format(id=target))

        if needs_dev_warning:
            if not self.config.get("dev_warn_ok"):
                await utils.answer(mx, self.strings.get("security_dev"))
                await asyncio.sleep(10)
                self.config.set("dev_warn_ok", True)
        elif from_community:
            await utils.answer(mx, self.strings.get("security_module"))
            await asyncio.sleep(5)

        try:
            await utils.answer(mx, self.strings.get("downloading"))
            code = await utils.request(url, return_type="text")
            path = Path(self.loader.community_path) / filename
            path.write_text(code, encoding="utf-8")
            
            await self.loader.register_module(path, mx, is_core=False)
            
            if path.stem in mx.active_modules:
                await utils.answer(mx, self.strings.get("done").format(name=filename))
            else:
                if path.exists(): path.unlink()
                await utils.answer(mx, self.strings.get("invalid_module"))
        except Exception as e: await utils.answer(mx, self.strings.get("error").format(err=str(e)))

    @loader.command()
    async def msearch(self, mx, event: MessageEvent):
        """<query> — Search in all repositories"""
        args = await utils.get_args(mx, event)
        if not args: return await utils.answer(mx, self.strings.get("search_no_query"))

        query = " ".join(args).lower()
        system_repo = self.config.get("repo_url")
        community_repos = await self._get_community_repos()
        
        output = ""
        found_any = False

        for r_url in [system_repo] + community_repos:
            try:
                data = await utils.request(f"{r_url}/index.json", return_type="json")
                results = [m for m in data.get("modules", []) if query in f"{m.get('id')} {m.get('name')} {m.get('description')}".lower()]
                
                if results:
                    found_any = True
                    is_system = (r_url == system_repo)
                    output += self.strings.get("search_header_system") if is_system else self.strings.get("search_header_community").format(url=r_url)
                    
                    prefix = "" if is_system else f"{self._get_prefix_from_url(r_url)}/"
                    
                    for mod in results:
                        output += self.strings.get("search_item").format(
                            name=mod.get("name"), 
                            id=mod.get("id"), 
                            version=mod.get("version"), 
                            desc=mod.get("description"),
                            cmd_id=f"{prefix}{mod.get('id')}"
                        )
            except: continue

        if not found_any: await utils.answer(mx, self.strings.get("search_empty").format(query=query))
        else: await utils.answer(mx, output)

    @loader.command()
    async def reload(self, mx, event: MessageEvent):
        """Reload all modules"""
        await utils.answer(mx, self.strings.get("reloading"))
        active = list(mx.active_modules.keys())
        for name in active:
            try: await self.loader.unload_module(name, mx)
            except: continue
        await self.loader.register_all(mx)
        msg = self.strings.get("reloaded_header")
        for name in mx.active_modules.keys():
            msg += self.strings.get("module_item").format(name=name)
        await utils.answer(mx, msg)

    @loader.command()
    async def unmd(self, mx, event: MessageEvent):
        """<name> — Unload and delete module"""
        args = await utils.get_args(mx, event)
        if not args: return await utils.answer(mx, self.strings.get("no_name"))
        name = args[0]
        if name not in mx.active_modules: return await utils.answer(mx, self.strings.get("not_found").format(name=name))
        try:
            await self.loader.unload_module(name, mx)
            path = Path(self.loader.community_path) / f"{name}.py"
            if path.exists(): path.unlink()
            await utils.answer(mx, self.strings.get("unloaded").format(name=name))
        except Exception as e: await utils.answer(mx, self.strings.get("error").format(err=str(e)))