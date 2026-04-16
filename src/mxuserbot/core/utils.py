import asyncio
import os
import platform
import shlex
from typing import Optional, Union

import aiohttp
import psutil

from mautrix.api import Method
from mautrix.crypto.attachments import encrypt_attachment
from mautrix.types import (
    EncryptedEvent,
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
)
from mautrix.util.formatter import parse_html

RPC_NAMESPACE = "com.ip-logger.msc4320.rpc"


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

    if not room_id:
        if event:
            room_id = event.room_id
        elif ctx_event:
            room_id = ctx_event.room_id
    
    if edit_id == -1:
        if event:
            edit_id = event.event_id
        elif ctx_event:
            edit_id = ctx_event.event_id
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
    room_id: Union[str, MessageEvent],
    url: str | None = None,
    file_bytes: bytes | None = None,
    info: ImageInfo | None = None,
    file_name: str | None = None,
    caption: str | None = None,
    relates_to=None,
    html: bool = True,
    **kwargs,
):
    """Downloads (if necessary), optionally encrypts, and sends an image to a specific room."""
    if not isinstance(room_id, str):
        room_id = room_id.room_id

    if isinstance(url, bytes) and file_bytes is None:
        file_bytes = url
        url = None

    if not file_bytes and url:
        if isinstance(url, str) and url.startswith("http"):
            file_bytes = await request(url, return_type="bytes")
        elif isinstance(url, str) and url.startswith("mxc://"):
            file_bytes = await mx.client.download_media(url)

    if not file_bytes:
        raise ValueError("Failed to retrieve image bytes")

    file_name = file_name or "image.png"
    mime_type = info.mimetype if info else "image/png"
    
    is_enc = await mx.client.state_store.is_encrypted(room_id)
    
    content = MediaMessageEventContent(
        msgtype=MessageType.IMAGE,
        body=file_name,
        info=info or ImageInfo(mimetype=mime_type),
    )

    if is_enc:
        encrypted_data, file_info = encrypt_attachment(file_bytes)
        mxc_url = await mx.client.upload_media(encrypted_data, mime_type=mime_type)
        file_info.url = mxc_url
        content.file = file_info
    else:
        mxc_url = await mx.client.upload_media(file_bytes, mime_type=mime_type)
        content.url = mxc_url

    if caption:
        content.body = caption
        if html:
            content.format = Format.HTML
            content.formatted_body = caption

    if relates_to:
        content.relates_to = relates_to

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