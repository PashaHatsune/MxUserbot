import asyncio
import contextvars
import logging
import os
import sys
import time
import traceback
from typing import Optional, Dict, Any

from loguru import logger
from mautrix.api import HTTPAPI, Method
from mautrix.client import Client
from mautrix.crypto import OlmMachine
from mautrix.crypto.store.asyncpg import PgCryptoStore, PgCryptoStateStore
from mautrix.types import (
    MessageEvent, EventType, StateEvent, RoomDirectoryVisibility, 
    ImageInfo
)
from mautrix.util.async_db import Database as MautrixDatabase
from mautrix.util.program import Program

from .core import utils
from .core.callback import CallBack
from .core.loader import Loader
from .core.security import SekaiSecurity
from .core.types import BotSASVerification, InterceptHandler, Config
from ..database import Database, AsyncSessionWrapper


class MXBotInterface:
    """Безопасная обертка для передачи в модули."""
    
    _current_event = contextvars.ContextVar("current_event")

    def __init__(self, bot: 'MXUserBot'):
        self._bot = bot
        self.version = bot.version
        
        self._get_prefix_func = bot.get_prefix
        self._log_to_room_func = bot.log_to_room
        self._should_ignore_event_func = bot.should_ignore_event

    @property
    def client(self) -> Client:
        return self._bot.client

    @property
    def sas_verifier(self) -> BotSASVerification:
        return self._bot.sas_verifier

    @property
    def active_modules(self) -> dict:
        return self._bot.active_modules

    def is_owner(self, sender_id: str) -> bool:
        """Динамически проверяет владельца через подсистему безопасности."""
        if self._bot.security:
            return self._bot.security.is_owner(sender_id)
        return False

    async def get_prefix(self) -> str:
        return await self._get_prefix_func()

    async def log_to_room(self, message: str):
        await self._log_to_room_func(message)

    def should_ignore_event(self, evt: MessageEvent) -> bool:
        return self._should_ignore_event_func(evt)

    async def send_message(self, room_id, content, **kwargs):
        """Проксирует отправку сырого контента в реальный клиент."""
        return await self.client.send_message(room_id, content, **kwargs)


class MXUserBot(Program):
    """Главный класс юзербота."""
    
    def __init__(self) -> None:
        super().__init__(
            module='main',
            name='sekai-user-bot',
            description="Sekai Userbot",
            command="-",
            version="0.6 | ALPHA",
            config_class=Config
        )
        self.client: Optional[Client] = None
        self._db: Optional[Database] = None
        self.all_modules: Optional[Loader] = None
        self.security: Optional[SekaiSecurity] = None
        
        self.active_modules: Dict[str, Any] = {}
        self.module_aliases: Dict[str, str] = {}  
        self.uri_cache: Dict[str, Any] = {}
        
        self.start_time: Optional[int] = None
        self.join_time: Optional[int] = None
        self.interface = MXBotInterface(self) 

        self.auth_completed = asyncio.Event()

    async def _setup_log_room(self) -> str:
        """Проверяет конфиг на наличие комнаты логов, создает её при необходимости."""
        log_room_id = self.config["matrix"]["log_room_id"]

        if log_room_id:
            return log_room_id

        self.log.info("Комната логов не найдена в конфиге. Создаю новую...")
        avatar_url = "mxc://pashahatsune.pp.ua/hGaNZRrDKOF5HlHjZ8VilRWj5QHFOXoy"

        initial_state =[
            {
                "type": "m.room.avatar",
                "state_key": "",
                "content": {"url": avatar_url}
            }
        ]

        new_room_id = await self.client.create_room(
            name="[LOGS] | MX-USERBOT",
            topic="Техническая комната для системных уведомлений и логов",
            is_direct=True,
            visibility=RoomDirectoryVisibility.PRIVATE,
            initial_state=initial_state
        )
        
        await self.client.join_room(new_room_id)
        await self.client.set_room_tag(new_room_id, "m.favourite", {"order": 0.0})
        await self.config.update_db_key("matrix.log_room_id", str(new_room_id))

        await utils.answer(
            self.interface, 
            "✅ | Комната логов успешно инициализирована.", 
            room_id=new_room_id,
            edit_id=None
        )

        self.config["matrix"]["log_room_id"] = str(new_room_id)
        self.config.save()
        
        self.log.info(f"Создана комната для логов: {new_room_id}. ID сохранен в config.yaml")
        return str(new_room_id)

    async def log_to_room(self, message: str) -> None:
        """Отправляет текстовое сообщение в комнату логов."""
        target_room = self.config["matrix"]["log_room_id"]
        
        if not target_room:
            self.log.warning("Комната логов не настроена, пропускаю отправку.")
            return

        try:
            await utils.send_image(
                mx=self.interface, 
                room_id=target_room,
                url="mxc://pashahatsune.pp.ua/ZPKENBwSwKgbFvrYWByGr1140eNqWQyL",
                caption=message,
                file_name="photo.png",
                info=ImageInfo(
                    width=600,
                    height=335,
                    mimetype="image/png"
                )
            )
        except Exception as e:
            self.log.error(f"Ошибка отправки лога в комнату: {e}")

    async def starts_with_command(self, body: str) -> bool:
        """Проверяет, начинается ли сообщение с активного префикса."""
        prefixes = await self._db.get(owner="core", key="prefix")
        return body.startswith(tuple(prefixes))

    def should_ignore_event(self, evt: MessageEvent) -> bool:
        if evt.timestamp < (self.start_time - 10000):
            logger.debug(f"Игнорирую старое событие: {evt.timestamp} < {self.start_time}")
            return True

        if not evt.content.body:
            return True
            
        return False

    async def is_owner(self, evt: StateEvent) -> bool:
        """Проверяет, является ли отправитель владельцем бота."""
        return evt.sender == self.config["owner"]

    def _setup_loguru(self) -> None:
        """Настройка форматирования и обработчиков для Loguru."""
        logging.basicConfig(handlers=[InterceptHandler()], level="INFO", force=True)
        logger.remove()
        
        log_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        logger.add(sys.stdout, format=log_format, colorize=True)

    def prepare_log(self) -> None:
        """Инициализация логирования (переопределение базового метода)."""
        self._setup_loguru()
        self.log = logger.bind(name=self.name)

    def prepare(self) -> None:
            """Подготовка бота к запуску."""
            super().prepare()
            
            self.add_startup_actions(self.run_api())
            
            self.add_startup_actions(self.setup_userbot())

    async def run_api(self):
        """Запуск FastAPI сервера без конфликтов сигналов."""
        from .core.web.api.main import setup_routes
        from fastapi import FastAPI
        import uvicorn
        
        app = FastAPI(title="Sekai Bot API")
        setup_routes(app, self, self.auth_completed)
        
        config = uvicorn.Config(
            app, 
            host="0.0.0.0", 
            port=8000, 
            log_level="info",
            loop="uvloop"
        )
        server = uvicorn.Server(config)

        server.install_signal_handlers = lambda: None

        async def safe_serve():
            try:
                await server.serve()
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            except Exception as e:
                self.log.error(f"API Server Error: {e}")

        asyncio.create_task(safe_serve())
        self.log.info("🌐 API сервер запущен на http://0.0.0.0:8000")

    async def get_args(self, body: str) -> str:
        """Извлекает аргументы команды (текст после команды)."""
        prefixes = await self._db.get(owner="core", key="prefix")
        for prefix in prefixes:
            if body.startswith(prefix):
                cmd_part = body[len(prefix):]
                parts = cmd_part.split(maxsplit=1)
                return parts[1] if len(parts) > 1 else ""
        return ""

    async def _load_prefixes(self) -> None:
        """Загрузка префиксов из БД при старте."""
        db_result = await self._db.get("core", "prefix", None)

        if not db_result:
            db_result = await self._db.set(
                owner='core',
                key="prefix",
                value=["."]
            )
            
        logger.success(f"Загружены префиксы: {await self._db.get(owner='core', key='prefix')}")

    async def _setup_security(self) -> None:
        """Инициализация подсистемы безопасности."""
        self.security = SekaiSecurity(self)
        await self.security.init_security()

    async def _cleanup_empty_rooms(self) -> None:
        """Вспомогательный метод: выход из пустых комнат при запуске."""
        joined_rooms = await self.client.get_joined_rooms()

        for room_id in joined_rooms:
            try:
                members = await self.client.get_joined_members(room_id)
                if len(members) == 1:
                    logger.info(f"В комнате {room_id} нет других пользователей. Покидаю...")
                    # await self.client.leave_room(room_id)
            except Exception as e:
                logger.error(f"Ошибка при очистке комнаты {room_id}: {e}")

    async def _register_handlers(self) -> None:
        """Вспомогательный метод: регистрация обработчиков событий (Matrix)."""
        cb = CallBack(self)
        
        self.client.add_event_handler(
            EventType.ROOM_MEMBER, 
            self.security.gate(cb.invite_cb)
        )
        self.client.add_event_handler(
            EventType.ROOM_MEMBER, 
            cb.memberevent_cb
        )

        if hasattr(cb, "message_cb"):
            self.client.add_event_handler(
                EventType.ROOM_MESSAGE, 
                cb.message_cb
            )

    async def get_prefix(self) -> str:
        """Безопасный геттер для получения основного префикса."""
        db_result = await self._db.get("core", "prefix")
        return db_result[0]

    async def setup_userbot(self) -> None:
        try:
            session_wrapper = AsyncSessionWrapper() 
            self._db = Database(session_wrapper)
            
            try:
                await self._db._sw.init_db()
            except Exception as e:
                if "already exists" in str(e).lower():
                    self.log.debug("Таблицы БД уже существуют, пропускаю создание.")
                else:
                    self.log.error(f"Ошибка инициализации БД: {e}")
                    raise e

            self.config.db = self._db
            await self.config.load_from_db()
            conf = self.config["matrix"]

            if not conf.get("access_token"):
                self.log.warning("⚠️ Данные авторизации не найдены!")
                self.log.info("🌐 Откройте http://127.0.0.1:8000/docs и выполните /api/auth")
                
                await self.auth_completed.wait()
                
                await self.config.load_from_db()
                conf = self.config["matrix"]
                self.log.success("✅ Авторизация получена. Запускаю криптографию...")

            db_path = os.path.join(os.getcwd(), "sekai.db")
            self.crypto_db = MautrixDatabase.create(f"sqlite:///{db_path}")
            await self.crypto_db.start() 
            
            await PgCryptoStore.upgrade_table.upgrade(self.crypto_db)
            await PgCryptoStateStore.upgrade_table.upgrade(self.crypto_db)

            self.state_store = PgCryptoStateStore(self.crypto_db)
            self.crypto_store = PgCryptoStore(conf["username"], "sekai_secret_pickle_key", self.crypto_db)

            self.client = Client(
                api=HTTPAPI(base_url=conf["base_url"]),
                state_store=self.state_store,
                sync_store=self.crypto_store
            )
            self.client.api.token = conf["access_token"]
            self.client.mxid = conf["username"]
            self.client.device_id = conf["device_id"]

            self.client.crypto = OlmMachine(self.client, self.crypto_store, self.state_store)
            self.client.crypto.allow_key_requests = True
            await self.client.crypto.load()

            self.sas_verifier = BotSASVerification(self.client)
            
            original_decrypt = self.client.crypto._decrypt_olm_event

            async def hooked_decrypt(evt):
                try:
                    decrypted = await original_decrypt(evt)
                    if decrypted:
                        # Проверяем тип события в расшифрованном виде
                        t = decrypted.type.t if hasattr(decrypted.type, "t") else str(decrypted.type)
                        if "m.key.verification" in t:
                            self.log.info(f"🔑 Поймано событие верификации: {t}")
                            # Запускаем обработку в фоне
                            asyncio.create_task(self.sas_verifier.handle_decrypted_event(decrypted))
                    return decrypted
                except Exception as e:
                    self.log.error(f"Ошибка расшифровки: {e}")
                    return None

            self.client.crypto._decrypt_olm_event = hooked_decrypt

            if not await self.crypto_store.get_device_id():
                await self.crypto_store.put_device_id(self.client.device_id)
                await self.client.crypto.share_keys()

            await self._setup_log_room()
            await self._setup_security()
            
            self.all_modules = Loader(self._db)
            await self.all_modules.register_all(self.interface)
            self.active_modules = self.all_modules.active_modules

            await self._load_prefixes()
            await self._register_handlers()

            self.start_time = int(time.time() * 1000)
            self.log.success(f"✅ UserBot запущен: {self.client.mxid}")
            
            await self.client.start(filter_data=None)

        except Exception as e:
            self.log.exception(f"Критическая ошибка запуска: {e}")


if __name__ == "__main__":
    try:
        bot = MXUserBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Работа бота завершена пользователем (Ctrl+C).")
    except Exception:
        traceback.print_exc(file=sys.stderr)