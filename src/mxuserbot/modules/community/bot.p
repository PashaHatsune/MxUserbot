import os
import asyncio
import time
from typing import Any, Optional
from mautrix.types import MessageEvent, EventType
from mautrix.util.program import Program
from mautrix.api import HTTPAPI
from mautrix.util.async_db import Database as MautrixDatabase
from mautrix.crypto.store.asyncpg import PgCryptoStore, PgCryptoStateStore
from mautrix.crypto import OlmMachine

from ...core import loader, utils
from ...core.types import UserBotClient, Config

class DroneProgram(Program):
    def __init__(self, bot_config: dict, owner_id: str) -> None:
        super().__init__(
            module='drone',
            name='sekai-drone',
            description="Sekai Drone Account",
            version="1.0.0",
            config_class=Config
        )
        self.bot_config = bot_config
        self.owner_id = owner_id # Передаем ID владельца, чтобы дрон слушался только его
        self.client: Optional[UserBotClient] = None
        self.start_time = int(time.time() * 1000)

    async def handle_drone_commands(self, evt: MessageEvent) -> None:
        """Обработчик команд специально для второго аккаунта"""
        # Игнорируем сообщения не от владельца и старые сообщения
        if evt.sender != self.owner_id or evt.timestamp < self.start_time:
            return

        body = evt.content.body
        if not body:
            return

        if body.strip().lower() == ".start":
            await self.client.send_text(
                evt.room_id, 
                f"🤖 <b>Drone Online</b>\nАккаунт: <code>{self.client.mxid}</code>\nСтатус: Работаю штатно."
            )

        if body.strip().lower() == ".ping":
            await self.client.send_text(evt.room_id, "Pong! (Drone Edition)")

    async def setup_userbot(self) -> None:
        conf = self.bot_config
        
        # db_path = os.path.join(os.getcwd(), "drone_crypto.db")
        # self.crypto_db = MautrixDatabase.create(f"sqlite:///{db_path}")
        # await self.crypto_db.start()

        # await PgCryptoStore.upgrade_table.upgrade(self.crypto_db)
        # await PgCryptoStateStore.upgrade_table.upgrade(self.crypto_db)

        # self.state_store = PgCryptoStateStore(self.crypto_db)
        # self.crypto_store = PgCryptoStore(conf["username"], "drone_secret_pickle_key", self.crypto_db)

        self.client = UserBotClient(
            api=HTTPAPI(base_url=conf["base_url"]),
            # state_store=self.state_store,
            # sync_store=self.crypto_store
        )

        await self.client.login(
            identifier=conf["username"],
            password=conf["password"],
            device_id=conf.get("device_id", "DRONE_DEVICE")
        )

        # self.client.crypto = OlmMachine(self.client, self.crypto_store, self.state_store)
        # await self.client.crypto.load()
        
        self.client.add_event_handler(EventType.ROOM_MESSAGE, self.handle_drone_commands)
        
        await self.client.start(filter_data=None)

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "DroneProgramControl",
        "_cls_doc": "Запуск второго аккаунта как полноценного Program-экземпляра.",
        "starting": "⏳ <b>[Drone]</b> Запуск второй программы...",
        "started": "✅ <b>[Drone]</b> Аккаунт <code>{mxid}</code> запущен.",
        "error": "❌ <b>[Drone]</b> Ошибка: <code>{err}</code>",
        "stopped": "🛑 <b>[Drone]</b> Программа остановлена.",
        "no_creds": "⚠️ Сначала настройте данные через <code>.dset</code>"
    }

    def __init__(self):
        self.drone: Optional[DroneProgram] = None

    async def _matrix_start(self, mx: Any):
        creds = await self._get("creds")
        if creds:
            asyncio.create_task(self.start_drone(mx, creds))

    async def start_drone(self, mx: Any, creds: dict):
        try:
            if self.drone and self.drone.client:
                self.drone.client.stop()
            
            self.drone = DroneProgram(creds, mx.client.mxid)
            await self.drone.setup_userbot()
        except Exception as e:
            self.logger.error(f"Критическая ошибка дрона: {e}")

    @loader.command()
    async def dset(self, mx: Any, event: MessageEvent):
        """<user> <pass> <url> — Установить данные дрона"""
        args = utils.get_args_raw(event.content.body).split()
        if len(args) < 3:
            return await mx.answer("Использование: <code>.dset user pass url</code>")
        
        base_url = args[2]
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"

        creds = {"username": args[0], "password": args[1], "base_url": base_url.rstrip("/")}
        await self._set("creds", creds)
        await mx.answer(self.strings.get("started").format(mxid=args[0]))

    @loader.command()
    async def drun(self, mx: Any, event: MessageEvent):
        """Запустить программу дрона"""
        creds = await self._get("creds")
        if not creds:
            return await mx.answer(self.strings.get("no_creds"))
        
        await mx.answer(self.strings.get("starting"))
        asyncio.create_task(self.start_drone(mx, creds))

    @loader.command()
    async def dstop(self, mx: Any, event: MessageEvent):
        """Остановить программу дрона"""
        if self.drone and self.drone.client:
            self.drone.client.stop()
            self.drone = None
            await mx.answer(self.strings.get("stopped"))
        else:
            await mx.answer("❌ Дрон не запущен.")