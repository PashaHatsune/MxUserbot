
# import re


import aiohttp
from mautrix.util.formatter import parse_html


from mautrix.types import EventID, EventType, Format, ImageInfo, MediaMessageEventContent, MessageEvent, MessageType, RelatesTo, RoomID, TextMessageEventContent



import platform
import psutil
import datetime

def get_platform():
    """Возвращает форматированную строку с данными о системе."""
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



def get_commands(cls):
    cmds = {}
    for attr_name in dir(cls):
        method = getattr(cls, attr_name)
        if callable(method) and getattr(method, 'is_command', False):
            cmds[method.command_name] = method
    return cmds

# def is_owner(event):
#     return event.sender in owners


# from loguru import logger
# навайбкожено, переписать
from mautrix.types import (
    RoomID, EventID, MessageType, RelatesTo, 
    TextMessageEventContent, Format, RelationType
)
from mautrix.util.formatter import parse_html
async def answer(
    mx,  # Это наш MXBotInterface
    text: str,
    html: bool = True,
    room_id: str = None,
    event: MessageEvent = None,
    edit_id: str | None = -1,
    **kwargs
) -> str:
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
        mx.logger.error("utils.answer() вызван без room_id и без контекста!")
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


from mautrix.util import markdown
from mautrix.crypto.attachments import encrypt_attachment

import io
from PIL import Image
from mautrix.types import ImageInfo # Убедись, что импортировано

import aiohttp
from mautrix.types import (
    MessageType, EventType, MediaMessageEventContent, 
    ImageInfo, Format
)
from mautrix.crypto.attachments import encrypt_attachment


import aiohttp
from typing import Union, Optional

async def request(
    url: str, 
    method: str = "GET", 
    return_type: str = "json", # json, text, bytes, или raw
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    **kwargs
) -> Union[dict, str, bytes, aiohttp.ClientResponse]:
    """Универсальный сокращатель HTTP-запросов"""
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, params=params, headers=headers, **kwargs) as response:
                if return_type == "json":
                    return await response.json()
                elif return_type == "text":
                    return await response.text()
                elif return_type == "bytes":
                    return await response.read()
                return response
        except Exception as e:
            return None

async def send_image(
    mx,
    room_id: Union[str, MessageEvent], # Разрешаем принимать и строку, и событие
    url: str | None = None,
    file_bytes: bytes | None = None,
    info: ImageInfo | None = None,
    file_name: str | None = None,
    caption: str | None = None,
    relates_to=None,
    html: bool = True,
    **kwargs,
):
    


    
    if not isinstance(room_id, str):
        room_id = room_id.room_id

    if isinstance(url, bytes) and file_bytes is None:
        file_bytes = url
        url = None

    if not file_bytes and url:
        if isinstance(url, str) and url.startswith("http"):
            # Используем твою новую функцию request, которую мы обсуждали!
            file_bytes = await request(url, return_type="bytes")
        elif isinstance(url, str) and url.startswith("mxc://"):
            file_bytes = await mx.client.download_media(url)

    if not file_bytes:
        raise ValueError("Не удалось получить байты изображения")

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



from mautrix.types import TextMessageEventContent

from mautrix.api import Method
from typing import Optional


RPC_NAMESPACE = "com.ip-logger.msc4320.rpc"
from typing import Optional, Union

async def set_rpc_media(
    mx,
    artist: str,
    album: str,
    track: str,
    length: Optional[int] = None,
    complete: Optional[int] = None,
    cover_art: Optional[Union[str, bytes]] = None, # Теперь принимает и байты, и ссылки
    player: Optional[str] = None,
    streaming_link: Optional[str] = None
):
    """
    Установить статус 'Слушает' (m.rpc.media). 
    Если cover_art — это URL или байты, она будет автоматически загружена в Matrix.
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
        if length is not None: data["progress"]["length"] = length
        if complete is not None: data["progress"]["complete"] = complete
    
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
    Установить статус 'Играет/Активность' (m.rpc.activity).
    :param name: Название активности/игры (обязательно)
    :param details: Детали (карта, уровень, текущее состояние)
    :param image: Ссылка MXC на иконку активности
    """
    data = {
        "type": f"{RPC_NAMESPACE}.activity",
        "name": name
    }

    if details: data["details"] = details
    if image: data["image"] = image

    endpoint = f"_matrix/client/v3/profile/{mx.client.mxid}/{RPC_NAMESPACE}"
    return await mx.client.api.request(Method.PUT, endpoint, content={RPC_NAMESPACE: data})


async def clear_rpc(mx):
    """
    Удалить Rich Presence статус согласно спецификации (DELETE или пустой PUT).
    """
    endpoint = f"_matrix/client/v3/profile/{mx.client.mxid}/{RPC_NAMESPACE}"
    return await mx.client.api.request(Method.DELETE, endpoint)






def get_args(message):
    import shlex
    """
    Get arguments from message
    :param message: Message or string to get arguments from
    :return: List of arguments
    """
    if not (message := getattr(message, "message", message)):
        return False

    if len(message := message.split(maxsplit=1)) <= 1:
        return []

    message = message[1]

    try:
        split = shlex.split(message)
    except ValueError:
        return message  # Cannot split, let's assume that it's just one long message



    return list(filter(lambda x: len(x) > 0, split))
from mautrix.types import EncryptedEvent

import os


from mautrix.types import EncryptedEvent

async def get_args_raw(mx, event) -> str:
    """
    1. Если в команде есть текст помимо первого аргумента -> возвращает аргументы (игнорирует реплай).
    2. Если в команде только 1 аргумент (или пусто) и есть реплай -> склеивает аргумент и текст реплая.
    3. Иначе -> возвращает аргументы команды.
    """
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
        relates = (
            getattr(event.content, "relates_to", None)
            or getattr(event.content, "_relates_to", None)
        )

        if relates and getattr(relates, "in_reply_to", None):
            reply_id = relates.in_reply_to.event_id

            replied_event = await mx.client.get_event(
                room_id=event.room_id,
                event_id=reply_id
            )

            if isinstance(replied_event, EncryptedEvent):
                try:
                    replied_event = await mx.client.crypto.decrypt_megolm_event(
                        replied_event
                    )
                except Exception:
                    pass

            reply_text = getattr(replied_event.content, "body", None)
            if reply_text:
                reply_text = reply_text.strip()
                
                if cmd_args:
                    return f"{cmd_args} {reply_text}"
                
                return reply_text

    except Exception:
        pass

    return cmd_args


def escape_html(text: str, /) -> str:  # sourcery skip
    """
    Pass all untrusted/potentially corrupt input here
    :param text: Text to escape
    :return: Escaped text
    """
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_quotes(text: str, /) -> str:
    """
    Escape quotes to html quotes
    :param text: Text to escape
    :return: Escaped text
    """
    return escape_html(text).replace('"', "&quot;")


def get_base_dir() -> str:
    """
    Get directory of this file
    :return: Directory of this file
    """
    return get_dir(__file__)


def get_dir(mod: str) -> str:
    """
    Get directory of given module
    :param mod: Module's `__file__` to get directory of
    :return: Directory of given module
    """
    return os.path.abspath(os.path.dirname(os.path.abspath(mod)))
