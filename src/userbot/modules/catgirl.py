from ..core import loader

import aiohttp

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "CatGirlModule",
        "_cls_doc": "Скидывает милых catgirl",
        "error_api": "Api умерло",
        "error_image": "Не удалось скачать/загрузить изображение на сервер"
    }

    @loader.command()
    async def catgirl(self, bot, room, event, args):
        """Отправляет фото кошко девочки через Api."""
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url="https://api.nekosia.cat/api/v1/images/catgirl"
            ) as r:
                if r.status != 200:
                    await bot.send_text(
                        room=room,
                        body=self.strings["error_api"]
                    )

                    return
                
                data = await r.json()

                url = data["image"]["original"]["url"]

                async with s.get(url) as img:
                    if img.status != 200:
                        await bot.send_text(
                            room=room,
                            body=self.strings["error_image"]
                        )

                    image = await img.read()

            await bot.send_image(
                room,
                image,
                body="catgirl"
            )
