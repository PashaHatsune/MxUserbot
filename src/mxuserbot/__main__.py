import os
import sys
import time
import logging
from typing import Optional, Dict, List, Any

from loguru import logger
from mautrix.client import Client
from mautrix.api import HTTPAPI
from mautrix.types import MessageEvent, EventType, StateEvent, RoomDirectoryVisibility
from mautrix.util.program import Program
from mautrix.util.config import BaseFileConfig, RecursiveDict, ConfigUpdateHelper

from .core.callback import CallBack
from .core.loader import Loader
from .core.security import SekaiSecurity 
from ..database import Database, AsyncSessionWrapper  


class InterceptHandler(logging.Handler):
    """Перехватчик стандартных логов Python и перенаправление их в Loguru."""
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
            
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
            
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, 
            record.getMessage()
        )


def setup_loguru(
    
) -> None:
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



from mautrix.util.config import BaseFileConfig, RecursiveDict, ConfigUpdateHelper
from ruamel.yaml.comments import CommentedMap
from typing import Any


from ..settings import config

class Config(BaseFileConfig):
    """
    Логика конфигурации через SQLite.
    Дефолтные значения подтягиваются из файла настроек settings.py
    """
    
    def __init__(self, path: str, base_path: str, db: Any = None) -> None:
        super().__init__(path, base_path)
        self.db = db
        self.owner = "core"
        
        self._default_values = {
            "matrix": {
                "base_url": config.matrix_config.base_url,
                "username": config.matrix_config.owner,
                "password": config.matrix_config.password.get_secret_value(),
                "device_id": config.matrix_config.device_id,
                "log_room_id": "",
                "owner": config.matrix_config.owner
            },
            "logging": {"version": 1}
        }
        
        self._data = RecursiveDict(self._default_values, CommentedMap)

    def load_base(self) -> RecursiveDict:
        """Метод для mautrix.util.program"""
        return RecursiveDict(self._default_values, CommentedMap)

    def load(self) -> None:
        """Файлы не используем"""
        pass

    def save(self) -> None:
        """Синхронный save ничего не делает, так как мы пишем в БД асинхронно"""
        pass

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("matrix")
        helper.copy("logging")

    async def load_from_db(self) -> None:
        """
        Загрузка из SQLite. Если ключа в БД нет, 
        останется значение из settings.py (из _default_values).
        """
        if not self.db:
            return

        async def fetch_recursive(data_dict: dict, prefix=""):
            for key, value in data_dict.items():
                full_key = f"{prefix}{key}"
                if isinstance(value, dict):
                    await fetch_recursive(value, f"{full_key}.")
                else:
                    db_value = await self.db.get(self.owner, full_key)
                    if db_value is not None:
                        self[full_key] = db_value

        await fetch_recursive(self._default_values)

    async def update_db_key(self, key: str, value: Any) -> None:
        """Обновление значения в памяти и в SQLite"""
        self[key] = value
        if self.db:
            await self.db.set(self.owner, key, value)


class MXUserBot(Program):
    """Главный класс юзербота."""
    
    def __init__(self) -> None:
        super().__init__(
            module='main',
            name='sekai-user-bot',
            description="Sekai Userbot",
            command="-",
            version="1.0.0",
            config_class=Config
        )
        self.client: Optional[Client] = None
        self.db: Optional[Database] = None
        self.all_modules: Optional[Loader] = None
        self.security: Optional[SekaiSecurity] = None
        
        self.active_modules: Dict[str, Any] = {}
        self.module_aliases: Dict[str, str] = {}  
        self.uri_cache: Dict[str, Any] = {}
        
        self.start_time: Optional[int] = None
        self.join_time: Optional[int] = None
        self.prefixes: List[str] = ["!", "."]


    async def _setup_log_room(self) -> str:
        """Проверяет конфиг на наличие комнаты логов, создает её при необходимости."""
        log_room_id = self.config["matrix"]["log_room_id"]

        if log_room_id:
            return log_room_id

        self.log.info("Комната логов не найдена в конфиге. Создаю новую...")
        owner_id = self.config["matrix"]["owner"]
        new_room_id = await self.client.create_room(
            name="Sekai Us1111erbot Logs",
            topic="Техническая комната для системных уведомлений и логов",
            is_direct=True,
            visibility=RoomDirectoryVisibility.PRIVATE,
            invitees=[owner_id]
        )

        logger.error(new_room_id)
        await self.client.join_room(new_room_id)
        await self.client.set_room_tag(new_room_id, "m.favourite", {"order": 0.0})
        await self.config.update_db_key("matrix.log_room_id", str(new_room_id))


        await self.client.send_text(new_room_id, "✅ Комната логов успешно инициализирована.")

        self.log.error(new_room_id)
        self.config["matrix"]["log_room_id"] = str(new_room_id)
        self.config.save()
        
        self.log.info(f"Создана комната для логов: {new_room_id}. ID сохранен в config.yaml")
        return str(new_room_id)


    async def log_to_room(self, message: str):
        """Отправляет текстовое сообщение в комнату логов."""
        target_room = self.config["matrix"]["log_room_id"]
        try:
            await self.client.send_text(target_room, message)
        except Exception as e:
            self.log.error(f"Ошибка отправки лога в комнату: {e}")


    def starts_with_command(
        self,
        body: str
    ) -> bool:
        """Проверяет, начинается ли сообщение с активного префикса."""
        return body.startswith(tuple(self.prefixes))


    def should_ignore_event(
        self,
        evt: MessageEvent
    ) -> bool:
        # if evt.sender == self.client.mxid:
        #     return True
        

        if evt.timestamp < (self.start_time - 10000):
            logger.debug(f"Игнорирую старое: {evt.timestamp} < {self.start_time}")
            return True

        if not evt.content.body:
            return True
            
        return False


    async def is_owner(
        self,
        evt: StateEvent
    ) -> bool:
        """Проверяет, является ли отправитель владельцем бота."""
        return evt.sender == self.config["owner"]


    def prepare_log(
        self
    ) -> None:
        """Инициализация логирования (переопределение базового метода)."""
        setup_loguru()
        self.log = logger.bind(name=self.name)


    def prepare(
        self
    ) -> None:
        """Подготовка бота к запуску (переопределение базового метода)."""
        super().prepare()
        config_mat = self.config["matrix"]

        self.client = Client(
            api=HTTPAPI(base_url=config_mat["base_url"])
        )

        self.add_startup_actions(self.setup_userbot())


    async def get_args(
        self, 
        body: str
    ) -> str:
        """Извлекает аргументы команды (текст после команды)."""
        for prefix in self.prefixes:
            if body.startswith(prefix):
                cmd_part = body[len(prefix):]
                parts = cmd_part.split(maxsplit=1)
                return parts[1] if len(parts) > 1 else ""
        return ""


    async def _load_prefixes(
        self
    ) -> None:
        """Загрузка префиксов из БД при старте."""
        db_result = await self.db.get("set_prefix", "prefix", None)

        if db_result:
            self.prefixes = db_result.value
            
        logger.info(f"Загружены префиксы: {self.prefixes}")


    async def _setup_security(
        self
    ) -> None:
        """Инициализация подсистемы безопасности."""
        self.security = SekaiSecurity(self)
        await self.security.init_security()


    async def _cleanup_empty_rooms(
        self
    ) -> None:
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


    async def _register_handlers(
        self
    ) -> None:
        """Вспомогательный метод: регистрация обработчиков событий (Matrix)."""
        cb = CallBack(self)
        
        self.client.add_event_handler(
            EventType.ROOM_MEMBER, 
            self.security.gate(cb.invite_cb)
        )

        self.client.add_event_handler(
            EventType.ROOM_MEMBER, 
            cb.memberevent_cb  # Было self.security.gate(cb.memberevent_cb)
        )

        if hasattr(cb, "message_cb"):
            self.client.add_event_handler(
                EventType.ROOM_MESSAGE, 
                cb.message_cb  # Было self.security.gate(cb.message_cb)
            )

    async def setup_userbot(self) -> None:
        try:
            session_wrapper = AsyncSessionWrapper() 
            self.db = Database(session_wrapper) 
            await self.db._sw.init_db()

            self.config.db = self.db
            await self.config.load_from_db()

            conf = self.config["matrix"]
            self.log.info("Выполняю вход в Matrix...")
            await self.client.login(
                identifier=conf["username"],
                password=conf["password"],
                device_id=conf["device_id"]
            )
            self.log.info("Успешный вход в систему!")

            log_room = await self._setup_log_room()

            self.all_modules = Loader(self.db)
            await self.all_modules.register_all(self)
            self.active_modules = self.all_modules.active_modules

            await self._setup_security()
            await self._load_prefixes()
            await self._register_handlers()

            import datetime
            await self.log_to_room(f"🚀 **Sekai UserBot** запущен!\n"
                                   f"Версия: `{self.version}`\n"
                                   f"Время: `{datetime.datetime.now().strftime('%H:%M:%S')}`")
            
            await self._cleanup_empty_rooms()
            self.start_time = int(time.time() * 1000)

            self.log.info("Запуск синхронизации Matrix...")
            await self.client.start(filter_data=conf["owner"])
            
        except Exception as e:
            self.log.exception(f"Критическая ошибка при запуске бота: {e}")


if __name__ == "__main__":
    try:
        bot = MXUserBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Работа бота завершена пользователем (Ctrl+C).")
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)