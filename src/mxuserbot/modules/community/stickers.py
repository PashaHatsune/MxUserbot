import aiohttp
import asyncio
import re
import uuid
import json
import io
import typing
from urllib.parse import quote
from PIL import Image
from typing import Any
from mautrix.types import MessageEvent

import av
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "StickerPort",
        "_cls_doc": "Импортирует стикеры (включая видео через PyAV)",
        "start": "<b>[StickerPort]</b> Начинаю импорт... Обработка видео может занять время.",
        "done": "<b>[StickerPort]</b> Готово! Импортировано {count} стикеров.",
        "error": "<b>[StickerPort]</b> Ошибка при импорте.",
        "bad_url": "<b>[StickerPort]</b> Неверная ссылка.",
    }

    BOT_TOKEN = "8662794033:AAEqJGRTP9Z_BctcSd5QIupqXoKl07ul360"

    async def _convert_video_to_webp(self, video_bytes: bytes) -> bytes:
        """Конвертирует WebM в анимированный WebP используя библиотеку av и Pillow"""
        try:
            return await asyncio.to_thread(self._sync_convert, video_bytes)
        except Exception as e:
            self.logger.error(f"Conversion error: {e}")
            return video_bytes

    def _sync_convert(self, video_bytes: bytes) -> bytes:
        input_file = io.BytesIO(video_bytes)
        container = av.open(input_file)
        
        frames = []
        max_frames = 30
        
        for frame in container.decode(video=0):
            img = frame.to_image().convert("RGBA")
            img.thumbnail((512, 512))
            frames.append(img)
            if len(frames) >= max_frames:
                break
        
        container.close()

        if not frames:
            return video_bytes

        output_buffer = io.BytesIO()
        frames[0].save(
            output_buffer,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=40, # ~25 FPS
            loop=0,
            quality=50,
            lossless=False
        )
        return output_buffer.getvalue()

    @loader.command()
    async def port(self, mx: Any, event: MessageEvent):
        """Портировать стикеры (.port <ссылка>)"""
        if not event.content.body:
            return
            
        body = event.content.body

        match = re.search(r"t\.me/addstickers/([A-Za-z0-9_]+)", body)
        if not match:
            await mx.client.send_text(
                room_id=event.room_id, 
                html=self.strings["bad_url"]
            )
            return

        pack_name = match.group(1)
        await mx.client.send_text(
            room_id=event.room_id, 
            html=self.strings["start"]
        )

        try:
            async with aiohttp.ClientSession() as session:
                tg_url = f"https://api.telegram.org/bot{self.BOT_TOKEN}/getStickerSet?name={pack_name}"
                async with session.get(tg_url) as r:
                    data = await r.json()

                if not data.get("ok"):
                    await mx.client.send_text(
                        room_id=event.room_id, 
                        html=self.strings["error"]
                    )
                    return

                result = data["result"]
                stickers = result["stickers"]
                title = result["title"]
                is_video = result.get("is_video", False)

                images = {}
                pack_id = f"tg_{pack_name.lower()}_{uuid.uuid4().hex[:6]}"
                
                for i, sticker in enumerate(stickers, 1):
                    file_id = sticker["file_id"]
                    
                    async with session.get(f"https://api.telegram.org/bot{self.BOT_TOKEN}/getFile?file_id={file_id}") as r:
                        f_data = await r.json()
                    
                    file_path = f_data["result"]["file_path"]
                    
                    async with session.get(f"https://api.telegram.org/file/bot{self.BOT_TOKEN}/{file_path}") as r:
                        file_bytes = await r.read()

                    if is_video or file_path.endswith(".webm"):
                        file_bytes = await self._convert_video_to_webp(file_bytes)
                    
                    
                    mxc_url = await mx.client.upload_media(
                        data=file_bytes, 
                        mime_type="image/webp", 
                        filename=f"{pack_name}_{i}.webp"
                    )
                    
                    # 2. Получаем размеры изображения через PIL (она у тебя уже импортирована)
                    with Image.open(io.BytesIO(file_bytes)) as img:
                        width, height = img.size

                    if mxc_url:
                        shortcode = f"tg_{i}"
                        images[shortcode] = {
                            "body": sticker.get("emoji", shortcode),
                            "url": mxc_url,
                            "info": {
                                "mimetype": "image/webp",
                                "w": width,
                                "h": height,
                                "size": len(file_bytes)
                            },
                            "usage": ["sticker"]
                        }

                state_type = "im.ponies.room_emotes"
                content = {
                    "pack": {
                        "display_name": f"TG: {title}",
                        "usage": ["sticker"],
                        "avatar_url": list(images.values())[0]["url"] if images else ""
                    },
                    "images": images
                }

                # Формируем контент пака
                content = {
                    "pack": {
                        "display_name": f"TG: {title}",
                        "usage": ["sticker"],
                        "avatar_url": list(images.values())[0]["url"] if images else ""
                    },
                    "images": images
                }

                # Отправляем как State Event (im.ponies.room_emotes)
                await mx.client.send_state_event(
                    room_id=event.room_id,
                    event_type="im.ponies.room_emotes",
                    content=content,
                    state_key=pack_id
                )

                await mx.client.send_text(
                    room_id=event.room_id, 
                    html=self.strings["done"].format(count=len(images))
                )
        except Exception as e:
            self.logger.exception(f"Port error: {e}")
            await mx.client.send_text(
                room_id=event.room_id, 
                html=self.strings["error"]
            )