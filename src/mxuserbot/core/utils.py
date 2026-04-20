import asyncio
import io
import os
import platform
import shlex
from typing import Optional, Union

from PIL import Image
import aiohttp
from loguru import logger
import psutil

from mautrix.api import Method
from mautrix.crypto.attachments import encrypt_attachment
from mautrix.types import (
    EncryptedEvent,
    EncryptedFile,
    EventType,
    Format,
    ImageInfo,
    MediaMessageEventContent,
    MessageEvent,
    MessageType,
    RelatesTo,
    RelationType,
    RoomID,
    TextMessageEventContent,
    ThumbnailInfo,
)
from mautrix.util.formatter import parse_html

RPC_NAMESPACE = "com.ip-logger.msc4320.rpc"



async def get_reply_event(mx, event: MessageEvent) -> Optional[MessageEvent]:
    """
    Retrieves the full event object of the message being replied to.
    Returns the event object or None if no reply or error.
    """
    relates = getattr(event.content, "relates_to", None) or getattr(event.content, "_relates_to", None)
    if not relates:
        return None
        
    reply_to = getattr(relates, "in_reply_to", None)
    if not reply_to or not reply_to.event_id:
        return None

    try:
        return await mx.client.get_event(event.room_id, reply_to.event_id)
    except Exception:
        return None

def get_platform() -> str:
    """Returns a formatted string containing system data."""
    os_info = f"{platform.system()} {platform.release()}"
    hostname = platform.node()
    ram = psutil.virtual_memory()
    
    used_ram = ram.used // 1024 // 1024
    total_ram = ram.total // 1024 // 1024
    ram_usage = f"{used_ram} / {total_ram} MB"
    
    cpu_usage = psutil.cpu_percent()

    return (
        f"<b>Сервер:</b> `{hostname}`<br>"
        f"<b>ОС:</b> `{os_info}`<br>"
        f"<b>Память:</b> `{ram_usage}`<br>"
        f"<b>Нагрузка CPU:</b> `{cpu_usage}%`"
    )


def get_commands(cls) -> dict:
    """Returns a dictionary of available commands for the given class."""
    cmds = {}
    for attr_name in dir(cls):
        method = getattr(cls, attr_name)
        if callable(method) and getattr(method, "is_command", False):
            cmds[method.command_name] = method
    return cmds


async def decrypt_event(mx, event_to_decrypt: EncryptedEvent, context_event: MessageEvent = None) -> str | None:
    """
    Universal utility for event decryption.
    If the key is missing, it requests it in the background.
    If context_event is provided, the bot will automatically reply to the user in the chat.
    Returns a decrypted string or None.
    """
    try:
        decrypted = await mx.client.crypto.decrypt_megolm_event(event_to_decrypt)
        return decrypted.content.body
    except Exception as de:
        if "no session" in str(de).lower() or "SessionNotFound" in str(type(de)):
            users_to_ask = {mx.client.mxid, event_to_decrypt.sender}
            from_devices = {}
            
            for user_id in users_to_ask:
                devices = await mx.client.crypto.crypto_store.get_devices(user_id)
                if devices:
                    from_devices[user_id] = {
                        dev_id: dev.identity_key 
                        for dev_id, dev in devices.items()
                    }

            if from_devices:
                if context_event:
                    await answer(mx, text="🔑 <b>У бота нет ключа для этого сообщения.</b>\nЗапрос отправлен твоим устройствам. Подожди 5-10 секунд и напиши команду заново (твой телефон должен быть онлайн).", event=context_event)
                
                asyncio.create_task(mx.client.crypto.request_room_key(
                    room_id=event_to_decrypt.room_id,
                    sender_key=event_to_decrypt.content.sender_key,
                    session_id=event_to_decrypt.content.session_id,
                    from_devices=from_devices
                ))
            else:
                if context_event:
                    await answer(mx, text="❌ <b>Ключ отсутствует</b>, и не у кого его запросить.", event=context_event)
            return None
        
        if context_event:
            await answer(mx, text=f"❌ <b>Ошибка дешифровки:</b> {de}", event=context_event)
        return None


async def get_reply_text(mx, event: MessageEvent) -> str | None | bool:
    """
    Extracts text from a reply with auto-decryption and key handling.
    Returns:
    - str (text) if successful
    - False if there is no reply
    - None if the key is missing or an error occurred
    """
    reply_to = getattr(event.content, "relates_to", None)
    if not reply_to or getattr(reply_to, "in_reply_to", None) is None:
        return False
        
    try:
        replied_event = await mx.client.get_event(event.room_id, reply_to.in_reply_to.event_id)
    except Exception as e:
        await answer(mx, text=f"❌ <b>Не удалось скачать сообщение:</b> {e}", event=event)
        return None
        
    if isinstance(replied_event, EncryptedEvent):
        return await decrypt_event(mx, replied_event, context_event=event)
    else:
        return getattr(replied_event.content, "body", "")


async def get_args_raw(mx, event) -> str:
    """Extracts command arguments handling both standard messages and replies (in silent mode)."""
    cmd_text = ""
    if isinstance(event, str):
        cmd_text = event
    elif hasattr(event, "content") and hasattr(event.content, "body"):
        cmd_text = event.content.body
    elif hasattr(event, "message"):
        cmd_text = event.message

    cmd_args = ""
    if cmd_text:
        cmd_text = cmd_text.strip()
        parts = cmd_text.split(maxsplit=1)
        cmd_args = parts[1].strip() if len(parts) > 1 else ""

    args_words_count = len(cmd_args.split())

    if args_words_count > 1:
        return cmd_args

    try:
        relates = getattr(event.content, "relates_to", None) or getattr(event.content, "_relates_to", None)
        if relates and getattr(relates, "in_reply_to", None):
            replied_event = await mx.client.get_event(room_id=event.room_id, event_id=relates.in_reply_to.event_id)

            if isinstance(replied_event, EncryptedEvent):
                reply_text = await decrypt_event(mx, replied_event, context_event=None)
            else:
                reply_text = getattr(replied_event.content, "body", None)
            
            if reply_text:
                reply_text = reply_text.strip()
                if cmd_args:
                    return f"{cmd_args} {reply_text}"
                return reply_text
    except Exception:
        pass

    return cmd_args


async def pin(mx, room_id: str, event_id: str, unpin: bool = False):

    try:
        try:
            current_state = await mx.client.get_state_event(room_id, EventType.ROOM_PINNED_EVENTS)
            pinned = current_state.get("pinned", []) if current_state else []
        except Exception:
            pinned = []

        if unpin:
            if event_id in pinned:
                pinned.remove(event_id)
        else:
            if event_id not in pinned:
                pinned.append(event_id)

        return await mx.client.send_state_event(
            room_id=room_id,
            event_type=EventType.ROOM_PINNED_EVENTS,
            content={"pinned": pinned},
            state_key=""
        )
    except Exception as e:
        mx.logger.error(f"Failed to pin/unpin {event_id}: {e}")
        return None


async def answer(
    mx,
    text: str,
    html: bool = True,
    room_id: str = None,
    event: MessageEvent = None,
    edit_id: str | None = -1,
    **kwargs
) -> str:
    """Sends or edits a message in the specified Matrix room."""
    ctx_event = None
    if hasattr(mx, "_current_event"):
        try:
            ctx_event = mx._current_event.get()
        except Exception:
            pass

    target_event = event or ctx_event

    if not room_id:
        if event:
            room_id = event.room_id
        elif ctx_event:
            room_id = ctx_event.room_id

    if edit_id == -1:
        if target_event:
            if target_event.sender == mx.client.mxid:
                edit_id = target_event.event_id
            else:
                edit_id = None
        else:
            edit_id = None

    if not room_id:
        mx.logger.error("utils.answer() called without room_id and context!")
        return ""

    plain_text = await parse_html(text) if html else text
    
    if edit_id:
        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=f" * {plain_text}",
            relates_to=RelatesTo(rel_type=RelationType.REPLACE, event_id=edit_id)
        )
        if html:
            content.format = Format.HTML
            content.formatted_body = text
            
        content.new_content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=plain_text,
            format=Format.HTML if html else None,
            formatted_body=text if html else None
        )
    else:
        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=plain_text,
            format=Format.HTML if html else None,
            formatted_body=text if html else None
        )

    allowed = ["timestamp", "txn_id"]
    matrix_kwargs = {k: v for k, v in kwargs.items() if k in allowed}

    return await mx.client.send_message(room_id, content, **matrix_kwargs)


async def request(
    url: str, 
    method: str = "GET", 
    return_type: str = "json",
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    **kwargs
) -> Union[dict, str, bytes, aiohttp.ClientResponse, None]:
    """Universal HTTP request shortcut supporting multiple return types."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, params=params, headers=headers, **kwargs) as response:
                if return_type == "json":
                    return await response.json(content_type=None)
                elif return_type == "text":
                    return await response.text()
                elif return_type == "bytes":
                    return await response.read()
                return response
        except Exception:
            return None


async def send_image(
    mx,
    room_id,
    file_bytes: bytes | None = None,
    url: str | None = None,
    file_name: str = "image.png",
    caption: str | None = None,
    info: ImageInfo | None = None,
    html: bool = True,
    **kwargs
):
    """Адекватная отправка изображений: E2EE + Thumbnail + Caption"""
    if not isinstance(room_id, str):
        room_id = room_id.room_id

    if not file_bytes and url:
        if url.startswith("http"):
            file_bytes = await request(url, return_type="bytes")
        elif url.startswith("mxc://"):
            file_bytes = await mx.client.download_media(url)
    
    if not file_bytes:
        raise ValueError("send_image: No bytes provided")

    img_obj = Image.open(io.BytesIO(file_bytes))
    w, h = img_obj.size
    
    thumb_bytes = None
    try:
        thumb_img = img_obj.copy()
        thumb_img.thumbnail((400, 400))
        t_io = io.BytesIO()
        thumb_img.save(t_io, format="PNG")
        thumb_bytes = t_io.getvalue()
        tw, th = thumb_img.size
    except: pass

    is_enc = await mx.client.state_store.is_encrypted(room_id) if mx.client.crypto else False
    
    if not info:
        info = ImageInfo(mimetype="image/png", size=len(file_bytes), width=w, height=h)

    content = MediaMessageEventContent(
        msgtype=MessageType.IMAGE,
        body=caption or file_name,
        info=info
    )

    if caption and html:
        content.format = Format.HTML
        content.formatted_body = caption

    if is_enc:
        await mx.client.crypto.wait_group_session_share(room_id)

        if thumb_bytes:
            et, ti = encrypt_attachment(thumb_bytes)
            ti.url = await mx.client.upload_media(et, mime_type="application/octet-stream")
            content.info.thumbnail_file = ti
            content.info.thumbnail_info = ThumbnailInfo(
                mimetype="image/png", size=len(thumb_bytes), width=tw, height=th
            )

        ed, fi = encrypt_attachment(file_bytes)
        fi.url = await mx.client.upload_media(ed, mime_type="application/octet-stream", filename=file_name)
        
        content.file = fi
        content.url = None
    else:
        if thumb_bytes:
            thumb_url = await mx.client.upload_media(thumb_bytes, mime_type="image/png")
            content.info.thumbnail_url = thumb_url
            content.info.thumbnail_info = ThumbnailInfo(mimetype="image/png", size=len(thumb_bytes), width=tw, height=th)
        
        content.url = await mx.client.upload_media(file_bytes, mime_type="application/octet-stream", filename=file_name)

    if "relates_to" in kwargs:
        content.relates_to = kwargs.pop("relates_to")

    return await mx.client.send_message_event(room_id, EventType.ROOM_MESSAGE, content, **kwargs)


async def set_rpc_media(
    mx,
    artist: str,
    album: str,
    track: str,
    length: Optional[int] = None,
    complete: Optional[int] = None,
    cover_art: Optional[Union[str, bytes]] = None,
    player: Optional[str] = None,
    streaming_link: Optional[str] = None
):
    """
    Set the 'Listening' status (m.rpc.media).
    If cover_art is a URL or bytes, it will be automatically uploaded to Matrix.
    """
    if cover_art:
        if isinstance(cover_art, bytes):
            mxc = await mx.client.upload_media(cover_art)
            cover_art = str(mxc)
            
        elif isinstance(cover_art, str) and cover_art.startswith(("http://", "https://")):
            img_bytes = await request(cover_art, return_type="bytes")
            if img_bytes:
                mxc = await mx.client.upload_media(img_bytes)
                cover_art = str(mxc)
            else:
                cover_art = None
                
    data = {
        "type": f"{RPC_NAMESPACE}.media",
        "artist": artist,
        "album": album,
        "track": track
    }

    if length is not None or complete is not None:
        data["progress"] = {}
        if length is not None:
            data["progress"]["length"] = length
        if complete is not None:
            data["progress"]["complete"] = complete
    
    if cover_art: 
        data["cover_art"] = cover_art
        
    if player: 
        data["player"] = player
        
    if streaming_link: 
        data["streaming_link"] = streaming_link

    endpoint = f"_matrix/client/v3/profile/{mx.client.mxid}/{RPC_NAMESPACE}"
    return await mx.client.api.request(Method.PUT, endpoint, content={RPC_NAMESPACE: data})


async def set_rpc_activity(
    mx,
    name: str,
    details: Optional[str] = None,
    image: Optional[str] = None
):
    """
    Set the 'Playing/Activity' status (m.rpc.activity).
    """
    data = {
        "type": f"{RPC_NAMESPACE}.activity",
        "name": name
    }

    if details:
        data["details"] = details
    if image:
        data["image"] = image

    endpoint = f"_matrix/client/v3/profile/{mx.client.mxid}/{RPC_NAMESPACE}"
    return await mx.client.api.request(Method.PUT, endpoint, content={RPC_NAMESPACE: data})


async def clear_rpc(mx):
    """Removes the Rich Presence status completely according to the specification."""
    endpoint = f"_matrix/client/v3/profile/{mx.client.mxid}/{RPC_NAMESPACE}"
    return await mx.client.api.request(Method.DELETE, endpoint)


async def get_args(mx, event) -> list:
    """
    Получает аргументы команды в виде списка. 
    Использует get_args_raw для извлечения текста (включая реплеи) 
    и shlex для парсинга (обработка кавычек).
    """
    raw = await get_args_raw(mx, event)
    
    if not raw:
        return []

    try:
        args = shlex.split(raw)
    except ValueError:
        args = raw.split()

    return list(filter(lambda x: len(x) > 0, args))


def escape_html(text: str, /) -> str:
    """Escape specific HTML characters in a string to avoid injection."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_quotes(text: str, /) -> str:
    """Escape quotes to their corresponding HTML entities."""
    return escape_html(text).replace('"', "&quot;")


def get_base_dir() -> str:
    """Get the absolute directory path of the current file."""
    return get_dir(__file__)


def get_dir(mod: str) -> str:
    """Get the absolute directory path of a given module."""
    return os.path.abspath(os.path.dirname(os.path.abspath(mod)))


async def is_dm(mx, room_id: str) -> bool:
    direct_data = await mx.client.get_account_data(EventType.DIRECT)

    return any(
        room_id in rooms
        for rooms in direct_data.values()
    )



import json
from pathlib import Path
from mautrix.types import EncryptedEvent, MessageType
from mautrix.crypto.attachments import decrypt_attachment

def convert_repo_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if "github.com" in url and "raw.githubusercontent.com" not in url:
        url = url.replace("github.com", "raw.githubusercontent.com")
        if "/tree/" in url:
            url = url.replace("/tree/", "/")
        else:
            url += "/main"
    return url

def get_prefix_from_url(url: str) -> str:
    parts = url.split("/")
    if "raw.githubusercontent.com" in url:
        return parts[3]
    return "community"

async def get_module_file(mx, event) -> tuple[str, bytes]:
    """Извлекает имя файла и его байты из сообщения Matrix (включая E2EE)."""
    if isinstance(event, EncryptedEvent):
        try:
            decrypted = await mx.client.crypto.decrypt_megolm_event(event)
            content = decrypted.content
        except Exception as e:
            raise ValueError("decrypt_err") from e
    else:
        content = event.content

    if content.msgtype != MessageType.FILE:
        raise ValueError("not_a_file")

    filename = content.body
    if content.file:
        ciphertext = await mx.client.download_media(content.file.url)
        code_bytes = decrypt_attachment(ciphertext, content.file.key.key, content.file.hashes.get("sha256"), content.file.iv)
    else:
        code_bytes = await mx.client.download_media(content.url)
        
    return filename, code_bytes



from pathlib import Path


async def install_module_file(loader, mx, filename: str, code: str) -> bool:
    """
    Сохраняет код модуля в папку community и регистрирует его.
    Используется в .mdl dev
    """
    try:
        path = Path(loader.community_path) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        
        path.write_text(code, encoding="utf-8")
        
        await loader.register_module(path, mx, is_core=False)
        
        return path.stem in mx.active_modules
    except Exception as e:
        mx.logger.error(f"Module install error: {e}")
        return False



async def uninstall_module(mx, name: str):
    """Выгружает и удаляет файл модуля."""
    loader = mx._bot.all_modules
    
    await loader.unload_module(name, mx)
    
    path = Path(loader.community_path) / f"{name}.py"
    if path.exists():
        path.unlink()


async def get_community_repo(db) -> list:
    """Безопасно извлекает список репозиториев из БД."""
    raw = await db.get("core", "community_repos")
    if not raw: return[]
    if isinstance(raw, list): return raw
    try: return json.loads(raw)
    except: return[]


async def set_community_repo(db, repos: list):
    """Сохраняет список репозиториев в БД."""
    await db.set("core", "community_repos", json.dumps(repos))


async def resolve_module_target(target: str, system_repo: str, community_repos: list, request_func) -> tuple[str, str, bool, bool]:
    """
    Превращает запрос пользователя в конкретную ссылку и имя файла.
    Возвращает: (url, filename, is_community, is_direct_link)
    """
    if target.startswith("http"):
        filename = target.split("/")[-1] if target.endswith(".py") else target.split("/")[-1] + ".py"
        return target, filename, True, True

    if "/" in target:
        user_prefix, mod_id = target.split("/", 1)
        for r_url in community_repos:
            if user_prefix.lower() in r_url.lower():
                try:
                    data = await request_func(f"{r_url}/index.json", return_type="json")
                    mod = next((m for m in data.get("modules",[]) if m.get("id") == mod_id), None)
                    if mod:
                        return f"{r_url}/modules/{mod['path']}", mod['path'], True, False
                except: continue
    else:
        try:
            data = await request_func(f"{system_repo}/index.json", return_type="json")
            mod = next((m for m in data.get("modules",[]) if m.get("id") == target), None)
            if mod:
                return f"{system_repo}/modules/{mod['path']}", mod['path'], False, False
        except: pass

    return None, None, False, False


async def search_modules_in_repo(query: str, system_repo: str, community_repos: list, request_func) -> list:
    """Ищет модули по всем репозиториям. Возвращает структурированный список результатов."""
    results = []
    for r_url in [system_repo] + community_repos:
        try:
            data = await request_func(f"{r_url}/index.json", return_type="json")
            matches = [m for m in data.get("modules", []) if query in f"{m.get('id')} {m.get('name')} {m.get('description')}".lower()]
            if matches:
                results.append({
                    "url": r_url, 
                    "is_system": r_url == system_repo, 
                    "modules": matches
                })
        except: continue
    return results


async def get_matrix_file_content(mx, event) -> tuple[str, bytes]:
    """
    Извлекает имя файла и его байты из сообщения Matrix (включая E2EE).
    Возвращает (filename, bytes).
    """
    if isinstance(event, EncryptedEvent):
        try:
            decrypted = await mx.client.crypto.decrypt_megolm_event(event)
            content = decrypted.content
        except Exception as e:
            raise ValueError("decrypt_err") from e
    else:
        content = event.content

    if content.msgtype != MessageType.FILE:
        raise ValueError("not_a_file")

    filename = content.body
    if content.file:
        ciphertext = await mx.client.download_media(content.file.url)
        code_bytes = decrypt_attachment(
            ciphertext, 
            content.file.key.key, 
            content.file.hashes.get("sha256"), 
            content.file.iv
        )
    else:
        code_bytes = await mx.client.download_media(content.url)
        
    return filename, code_bytes

import os
import subprocess
from pathlib import Path
from typing import List

COMM_DIR = Path(__file__).resolve().parents[1] / "modules" / "community"

def _get_safe_path(filename: str) -> Path:
    """Гарантирует, что путь находится внутри community и файл не является кодом"""
    safe_name = os.path.basename(filename)
    final_path = (COMM_DIR / safe_name).resolve()

    if COMM_DIR not in final_path.parents and final_path != COMM_DIR:
        raise PermissionError("Security: Access restricted to community folder only.")

    forbidden_ext = {".py", ".pyc", ".sh", ".bash", ".exe", ".so", ".dll"}
    if final_path.suffix.lower() in forbidden_ext:
        raise PermissionError(f"Security: Prohibited file extension: {final_path.suffix}")

    return final_path

async def safe_save(file_bytes: bytes, filename: str) -> str:
    """Ядро сохраняет байты в файл внутри community"""
    path = _get_safe_path(filename)
    with open(path, "wb") as f:
        f.write(file_bytes)
    return str(path)

async def safe_remove(filename: str):
    """Ядро удаляет файл внутри community"""
    path = _get_safe_path(filename)
    if path.exists():
        os.remove(path)

async def ffmpeg_run(args: List[str]) -> bool:
    """
    Универсальный запуск FFmpeg. 
    Автоматически проверяет все пути в аргументах на безопасность.
    """
    safe_args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    
    # Сканируем аргументы: если это путь, прогоняем через фильтр
    for arg in args:
        if "/" in arg or "\\" in arg or "." in arg:
            try:
                # Если аргумент похож на путь, делаем его безопасным
                safe_args.append(str(_get_safe_path(arg)))
            except:
                safe_args.append(arg) # Если не путь (например, кодек), оставляем
        else:
            safe_args.append(arg)

    process = await asyncio.create_subprocess_exec(
        *safe_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    await process.wait()
    return process.returncode == 0