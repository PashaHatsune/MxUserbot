import asyncio
import contextvars
import logging
import os
import sys
import time
import traceback
from typing import Optional, Dict, Any

from loguru import logger
from mautrix.api import HTTPAPI
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
from .core.types import BotSASVerification, InterceptHandler
from ..database import Database, AsyncSessionWrapper


from mautrix.util.async_db import Database as MautrixDatabase
from mautrix.util.program import Program
from mautrix.util.config import BaseFileConfig, ConfigUpdateHelper, RecursiveDict
from ruamel.yaml.comments import CommentedMap

from mautrix.errors import MatrixConnectionError
class Config(BaseFileConfig):
    """
    Dummy config class to satisfy mautrix Program requirements.
    We don't use file config anymore, everything is handled via database.
    """
    def __init__(self, path: str, base_path: str) -> None:
        super().__init__(path, base_path)
        self._data = RecursiveDict({"logging": {"version": 1}}, CommentedMap)

    def load_base(self) -> RecursiveDict:
        return RecursiveDict({"logging": {"version": 1}}, CommentedMap)

    def load(self) -> None: pass
    def save(self) -> None: pass
    def do_update(self, helper: ConfigUpdateHelper) -> None: pass

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

from mautrix.client import InternalEventType

class MXUserBot(Program):
    """Main userbot class."""
    
    def __init__(self) -> None:
        super().__init__(
            module='main',
            name='MXUserBot',
            description="MXUserbot - matrix userbot.",
            command="-",
            version="1.5 | BETA",
            config_class=Config
        )
        self.client: Optional[Client] = None
        self.logger = logger
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
        """Checks DB for log room, creates it if necessary."""
        log_room_id = await self._db.get("core", "log_room_id")

        if log_room_id:
            return log_room_id

        self.log.info("Log room not found in database. Creating a new one...")
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
            topic="Technical room for system notifications and logs",
            is_direct=True,
            visibility=RoomDirectoryVisibility.PRIVATE,
            initial_state=initial_state
        )
        
        await self.client.join_room(new_room_id)
        await self.client.set_room_tag(new_room_id, "m.favourite", {"order": 0.0})
        
        await self._db.set("core", "log_room_id", str(new_room_id))

        await utils.answer(
            self.interface, 
            "✅ | Log room successfully initialized.", 
            room_id=new_room_id,
            edit_id=None
        )
        
        self.log.info(f"Created log room: {new_room_id}. ID saved to DB.")
        return str(new_room_id)

    async def log_to_room(self, message: str) -> None:
        """Sends a text message to the log room."""
        target_room = await self._db.get("core", "log_room_id")
        
        if not target_room:
            self.log.warning("Log room is not set, skipping log sending.")
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
            self.log.error(f"Error sending log to room: {e}")

    async def starts_with_command(self, body: str) -> bool:
        """Checks if the message starts with an active prefix."""
        prefixes = await self._db.get(owner="core", key="prefix")
        return body.startswith(tuple(prefixes))

    def should_ignore_event(self, evt: MessageEvent) -> bool:
        if evt.timestamp < (self.start_time - 10000):
            logger.debug(f"Ignoring old event: {evt.timestamp} < {self.start_time}")
            return True

        if not evt.content.body:
            return True
            
        return False

    async def is_owner(self, evt: StateEvent) -> bool:
        """Checks if the sender is the bot owner."""
        owner = await self._db.get("core", "owner")
        return evt.sender == owner

    def _setup_loguru(self) -> None:
        """Loguru formatting and handlers setup."""
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
        """Logging initialization."""
        self._setup_loguru()
        self.log = logger.bind(name=self.name)

    def prepare(self) -> None:
        """Preparing the bot for startup."""
        super().prepare()
        self.add_startup_actions(self.run_api())
        self.add_startup_actions(self.setup_userbot())

    async def run_api(self):
        """Launching FastAPI server without signal conflicts."""
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
        self.log.info("🌐 API server running at http://0.0.0.0:8000")

    async def get_args(self, body: str) -> str:
        """Extracts command arguments (text after the command)."""
        prefixes = await self._db.get(owner="core", key="prefix")
        for prefix in prefixes:
            if body.startswith(prefix):
                cmd_part = body[len(prefix):]
                parts = cmd_part.split(maxsplit=1)
                return parts[1] if len(parts) > 1 else ""
        return ""

    async def _load_prefixes(self) -> None:
        """Loading prefixes from DB at startup."""
        db_result = await self._db.get("core", "prefix", None)

        if not db_result:
            db_result = await self._db.set(
                owner='core',
                key="prefix",
                value=["."]
            )
            
        logger.success(f"Prefixes loaded: {await self._db.get(owner='core', key='prefix')}")

    async def _setup_security(self) -> None:
        """Initializing security subsystem."""
        self.security = SekaiSecurity(self)
        await self.security.init_security()

    async def _register_handlers(self) -> None:
        """Registering event handlers (Matrix)."""
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
        """Safe getter for receiving the main prefix."""
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
            access_token = await self._db.get("core", "access_token")

            if not access_token:
                self.log.warning("⚠️ | Authorization data not found!!")
                self.log.info("🌐 | open http://127.0.0.1:8000/ to authorize.")
                
                await self.auth_completed.wait()
                access_token = await self._db.get("core", "access_token")
                
                self.log.success("✅ Авторизация получена. Запускаю криптографию...")

            db_path = os.path.join(os.getcwd(), "sekai.db")
            self.crypto_db = MautrixDatabase.create(f"sqlite:///{db_path}")
            await self.crypto_db.start() 

            base_url = await self._db.get("core", "base_url")
            username = await self._db.get("core", "username")
            device_id = await self._db.get("core", "device_id")
            
            await PgCryptoStore.upgrade_table.upgrade(self.crypto_db)
            await PgCryptoStateStore.upgrade_table.upgrade(self.crypto_db)

            self.state_store = PgCryptoStateStore(self.crypto_db)
            self.crypto_store = PgCryptoStore(username, "sekai_secret_pickle_key", self.crypto_db)

            self.client = Client(
                api=HTTPAPI(base_url=base_url),
                state_store=self.state_store,
                sync_store=self.crypto_store
            )
            self.client.api.token = access_token
            self.client.mxid = username
            self.client.device_id = device_id

            self.client.crypto = OlmMachine(self.client, self.crypto_store, self.state_store)
            self.client.crypto.allow_key_requests = True
            await self.client.crypto.load()

            self.sas_verifier = BotSASVerification(self.client)
            
            original_decrypt = self.client.crypto._decrypt_olm_event

            async def hooked_decrypt(evt):
                try:
                    decrypted = await original_decrypt(evt)
                    if decrypted:
                        t = decrypted.type.t if hasattr(decrypted.type, "t") else str(decrypted.type)
                        if "m.key.verification" in t:
                            self.log.info(f"🔑 | verif request: {t}")
                            asyncio.create_task(self.sas_verifier.handle_decrypted_event(decrypted))
                    return decrypted
                except Exception as e:
                    self.log.error(f"Oshibka rashifrovki: {e}")
                    return None

            self.client.crypto._decrypt_olm_event = hooked_decrypt

            if not await self.crypto_store.get_device_id():
                await self.crypto_store.put_device_id(self.client.device_id)
                await self.client.crypto.share_keys()


            self.log.info("📡 | Checking connection to Matrix server...")
            while True:
                try:
                    await self.client.whoami()
                    break # Connection success
                except (MatrixConnectionError, OSError):
                    self.log.error("🌐 Network is unreachable. Retrying in 5 seconds...")
                    await asyncio.sleep(5)


            await self._setup_log_room()
            await self._setup_security()
            
            self.all_modules = Loader(self._db)
            await self.all_modules.register_all(self.interface)
            self.active_modules = self.all_modules.active_modules

            await self._load_prefixes()
            await self._register_handlers()

            self.start_time = int(time.time() * 1000)
            
            sync_started = asyncio.Event()

            async def handle_first_sync(data):
                if not sync_started.is_set():
                    sync_started.set()
                    self.client.remove_event_handler(InternalEventType.SYNC_SUCCESSFUL, handle_first_sync)

            self.client.add_event_handler(InternalEventType.SYNC_SUCCESSFUL, handle_first_sync)

            self.log.info("📡 | Connecting to Matrix server...")
            sync_task = self.client.start(filter_data=None)
            
            if asyncio.iscoroutine(sync_task):
                sync_task = asyncio.create_task(sync_task)

            try:
                await asyncio.wait_for(sync_started.wait(), timeout=30)
                self.log.success(f"✅ | UserBot successfully synced and running: {self.client.mxid}")
                
                await self.log_to_room(f"🚀 MXUserBot is online!\nUser: {self.client.mxid}")
                
            except asyncio.TimeoutError:
                self.log.error("❌ | Connection timeout: Server is not responding to sync.")
            

        except Exception as e:

            self.log.exception(f"{e}")
        except MatrixConnectionError:
            print(1)
            sys.exit(1)


if __name__ == "__main__":
    try:
        bot = MXUserBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Работа бота завершена пользователем (Ctrl+C).")
        sys.exit(1)
    except Exception:
        traceback.print_exc(file=sys.stderr)