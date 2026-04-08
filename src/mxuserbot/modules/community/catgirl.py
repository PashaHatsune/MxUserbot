import aiohttp
from mautrix.types import (
    MessageEvent, ImageInfo, EventType, 
    MediaMessageEventContent, MessageType
)
from mautrix.crypto.attachments import encrypt_attachment
from ...core import loader
from mautrix.client import Client

@loader.tds
class MatrixModule(loader.Module):
    strings = {"name": "CatGirlModule", "error": "Ошибка API", "_cls_doc": "1"}

    @loader.command()
    async def catgirl(self, mx: Client, event: MessageEvent):
        """Отправляет фото кошко-девочки (E2EE Ready)."""
        async with aiohttp.ClientSession() as s:
            # 1. Получаем ссылку
            async with s.get("https://api.nekosia.cat/api/v1/images/catgirl") as r:
                if r.status != 200: 
                    return await mx.send_text(event.room_id, self.strings["error"])
                data = await r.json()
                url = data["image"]["original"]["url"]
                filename = url.split("/")[-1] or "catgirl.png"
            
            # 2. Скачиваем картинку
            async with s.get(url) as img:
                image_bytes = await img.read()

        # 3. Подготовка
        info = ImageInfo(mimetype="image/png", size=len(image_bytes))
        is_enc = await mx.state_store.is_encrypted(event.room_id)

        # Используем MediaMessageEventContent (он есть в вашей документации)
        if is_enc:
            # Шифруем файл для E2EE чатов
            data, file_info = encrypt_attachment(image_bytes)
            mxc = await mx.client.upload_media(data, mime_type="application/octet-stream")
            file_info.url = mxc
            
            content = MediaMessageEventContent(
                msgtype=MessageType.IMAGE,
                body=filename,
                info=info,
                file=file_info  # Поле для зашифрованного файла
            )
        else:
            # Обычная загрузка для открытых чатов
            mxc = await mx.client.upload_media(image_bytes, mime_type="image/png")
            content = MediaMessageEventContent(
                msgtype=MessageType.IMAGE,
                body=filename,
                info=info,
                url=mxc  # Прямая ссылка
            )

        # 4. Отправляем через send_message_event
        # Мы не используем send_image, так как он в вашей версии не принимает зашифрованный 'file'
        await mx.client.send_message_event(
            room_id=event.room_id,
            event_type=EventType.ROOM_MESSAGE,
            content=content
        )