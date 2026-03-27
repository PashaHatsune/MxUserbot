import time
import asyncio
import typing

from loguru import logger
from nio import InviteEvent, RoomMemberEvent, RoomMessageText, SyncError, AsyncClient

from .methods import Methods
from .callback import CallBack
from .loader import Loader
from .security import SekaiSecurity


if typing.TYPE_CHECKING:
    from ...database.methods import Database


class Bot(Methods):
    def __init__(self, db: 'Database', client=None):
        
        self.db: Database = db
        self.client: AsyncClient = client
        
        self.all_modules = Loader(self.db)
        self.active_modules = {}
        self.module_aliases = {}  
        
        self.version = "1"
        self.uri_cache = dict()
        
        self.bot_task = None
        self.poll_task = None
        self.stopping = False
        self.start_time = int(time.time() * 1000)
        self.jointime = None

        self.security: SekaiSecurity = None # Добавь в init


    def setup_callbacks(self):
        """Метод для регистрации всех обработчиков событий"""
        if self.client is None:
            raise RuntimeError("Сначала нужно инициализировать self.client!")

        cb_handler = CallBack(self)
        
        # self.client.add_event_callback(cb_handler.invite_cb, InviteEvent)
        # self.client.add_event_callback(cb_handler.memberevent_cb, RoomMemberEvent)
        
        # if hasattr(cb_handler, "message_cb"):
        #     self.client.add_event_callback(cb_handler.message_cb, RoomMessageText)

        # self.client.add_event_callback(cb_handler.message_cb, RoomMessage)
        
        self.client.add_event_callback(
            self.security.gate(cb_handler.invite_cb), 
            InviteEvent
        )
        
        self.client.add_event_callback(
            self.security.gate(cb_handler.memberevent_cb), 
            RoomMemberEvent
        )
        
        if hasattr(cb_handler, "message_cb"):
            self.client.add_event_callback(
                self.security.gate(cb_handler.message_cb), 
                RoomMessageText
            )

    async def setup_security(self):
        """Инициализация безопасности"""
        self.security = SekaiSecurity(self)
        await self.security.init_security()

    async def save_settings(self):
        """Синхронизируем текущие настройки модулей в базу данных"""
        for name, instance in self.active_modules.items():
            if hasattr(instance, "get_settings"):
                try:

                    await self.db.set(name, "__config__", instance.get_settings())
                except Exception:
                    logger.exception(f'Failed to save settings for {name}')
        await self.db.set("core", "uri_cache", self.uri_cache)


    def stop(self):
        logger.info(f'Stopping {len(self.active_modules)} modules..')
        for modulename, moduleobject in self.active_modules.items():
            try:
                moduleobject._matrix_stop(self)
            except Exception:
                logger.exception(f'unhandled exception from {modulename}.matrix_stop')
        logger.info(f'All modules stopped.')


    async def poll_timer(self):
        """Фоновый цикл для matrix_poll (раз в 10 сек)"""
        pollcount = 0
        while True:
            pollcount += 1
            for instance in self.active_modules.values():
                if getattr(instance, "enabled", True) and hasattr(instance, "matrix_poll"):
                    try:
                        await instance.matrix_poll(self, pollcount)
                    except Exception:
                        logger.exception(f'Error polling module {instance.name}')
            await asyncio.sleep(10)





# ТУТ ВРЕМЕННО ВСПОМОГАТЕЛЬНЫЕ
    def starts_with_command(self, body):
        """Checks if body starts with ! and has one or more letters after it"""
        import re
        return re.match(r"^!\w.*", body) is not None


    def should_ignore_event(self, event):
        # if event.sender == self.client.user_id:
        #     return True

        # event.server_timestamp приходит в миллисекундах
        if hasattr(event, 'server_timestamp'):
            if event.server_timestamp < self.start_time:
                return True

        if "org.vranki.hemppa.ignore" in event.source.get('content', {}):
            return True

        return False


    def load_settings(bot, data):
        if not data:
            return
        if not data.get('module_settings'):
            return
        for modulename, moduleobject in bot.active_modules.items():
            if data['module_settings'].get(modulename):
                try:
                    moduleobject.set_settings(
                        data['module_settings'][modulename])
                except Exception:
                    logger.exception(f'unhandled exception {modulename}.set_settings')


    async def run(self):
            """Главный метод запуска бота"""
            sync_response = await self.client.sync()
            
            if type(sync_response) == SyncError:
                logger.error(f"Received Sync Error when trying to do initial sync! Error message is: %s", sync_response.message)
            else:
                await self.db._sw.init_db()
                leave_empty_rooms = await self.db.get("core", "leave_empty_rooms", True)
                join_on_invite = await self.db.get("core", "join_on_invite", False)
                owners = await self.db.get("core", "owners", [])

                for roomid, room in self.client.rooms.items():
                    # logger.info(f"Bot is on '{room.display_name}'({roomid}) with {len(room.users)} users")
                    if len(room.users) == 1 and leave_empty_rooms:
                        logger.info(f'Room {roomid} has no other users - leaving it.')
                        await self.client.room_leave(roomid)

                if self.client.logged_in:
                    self.poll_task = asyncio.create_task(self.poll_timer())

                    data = self.get_account_data()
                    print(data)
                    if data is None:
                        logger.info("Initializing account data for the first time...")
                        self.save_settings() 

                    await self.all_modules.register_all(self)
                    self.active_modules = self.all_modules.active_modules

                    # await self.start()
                    await self.setup_security()

                    self.setup_callbacks()

                    if join_on_invite:
                        logger.info('Note: Bot will join rooms if invited (Auto-join: ENABLED)')
                    
                    logger.info('Bot running as %s, owners %s', self.client.user, owners)

                    self.bot_task = asyncio.create_task(
                        self.client.sync_forever(timeout=30000)
                    )
                    await self.bot_task
                else:
                    logger.error('Login failed! Check credentials.')


    async def shutdown(self):
        await self.client.close()

    async def close(self):
        try:
            await self.client.close()
            logger.info("Connection closed")
        except Exception as ex:
            logger.error("Error closing client: %s", ex)

    def handle_exit(self, signame, loop):
        logger.info(f"Received signal {signame}")
        if self.poll_task:
            self.poll_task.cancel()
        self.bot_task.cancel()
        self.stop()