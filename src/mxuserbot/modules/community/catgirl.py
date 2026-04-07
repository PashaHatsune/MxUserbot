from typing import Any
import aiohttp
from mautrix.types import MessageEvent
from ...core import loader


@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "CatGirlModule",
        "_cls_doc": "Скидывает милых catgirl",
        "error_api": "Api умерло",
        "error_image": "Не удалось скачать/загрузить изображение на сервер"
    }

    @loader.command()
    async def catgirl(self, mx, event: MessageEvent):
        """Отправляет фото кошко-девочки через API."""
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.nekosia.cat/api/v1/images/catgirl") as r:
                if r.status != 200:
                    return await mx.client.send_text(
                        room_id=event.room_id, 
                        html=self.strings["error_api"]
                    )
                
                data = await r.json()
                url = data["image"]["original"]["url"]
                filename = url.split("/")[-1] or "catgirl.png"

                async with s.get(url) as img:
                    if img.status != 200:
                        return await mx.client.send_text(
                            room_id=event.room_id, 
                            html=self.strings["error_image"]
                        )
                    image_bytes = await img.read()

                    mxc = await mx.client.upload_media(
                        data=image_bytes,
                        mime_type="image/png",
                        filename=filename

                    )

            await mx.client.send_image(
                room_id=event.room_id,
                url=mxc
            )