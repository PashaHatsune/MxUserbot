from mautrix.types import MessageEvent

from ...core import loader
from ...core import utils


import asyncio

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "TestModule",
        "_cls_doc": "Тестовый модуль",
        "test_text": "<b>Привет! Это тестовый текст</b>"
    }

    @loader.command()
    async def test(self, mx, event):
        """Простейшая команда"""
        # Отредактирует сообщение .test
        await mx.answer("🎶 <b>Играет:</b> <code>Ghost of a smile</code>")
        
        await asyncio.sleep(2)
        
        # Отредактирует это же сообщение еще раз
        await mx.answer("Текст изменился автоматически!")