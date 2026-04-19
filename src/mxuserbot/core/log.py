import asyncio
from loguru import logger


class MXLog:
    def __init__(self, bot):
        self.bot = bot
        self.queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker())

    def write(self, message):
        self.queue.put_nowait(message)

    async def _worker(self):
        while True:
            try:
                logs_to_send =[]
                log = await self.queue.get()
                logs_to_send.append(log)

                while not self.queue.empty():
                    try:
                        logs_to_send.append(self.queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if not logs_to_send:
                    continue

                text_chunk = "".join(logs_to_send)
                
                if len(text_chunk) > 4000:
                    text_chunk = text_chunk[:3950] + "\n\n..."

                room_id = await self.bot._db.get("core", "log_room_id")
                
                if room_id:
                    await self.bot.client.send_notice(
                        room_id,
                        html=f"<pre><code>{text_chunk}</code></pre>"
                    )
                
                await asyncio.sleep(2)

            except Exception as e:
                logger.exception(e)