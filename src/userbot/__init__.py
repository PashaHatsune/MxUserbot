
import asyncio
import functools
from loguru import logger
from nio import InviteEvent, RoomMessageText, RoomMemberEvent, SyncError

from .bot import Bot
from .modules.core.message_cb import message_cb
from .modules.core.init_client import init_client
from .modules.core.load_settings import load_settings 
from .modules.core.invite_cb import invite_cb, memberevent_cb
from .modules.core.account_settings import get_account_data, set_account_data
from .registry import active_modules, leave_empty_rooms, join_on_invite, invite_whitelist, owners, appid, version, uri_cache


bot_task = None
poll_task = None
client = init_client()


def save_settings(bot):
    module_settings = dict()
    for modulename, moduleobject in active_modules.items():
        try:
            module_settings[modulename] = moduleobject.get_settings()
        except Exception:
            logger.exception(f'unhandled exception {modulename}.get_settings')
    data = {appid: version, 'module_settings': module_settings, 'uri_cache': uri_cache}
    set_account_data(data)


def start(bot):
    load_settings(get_account_data())
    enabled_modules = [module for module_name, module in active_modules.items() if module.enabled]
    logger.info(f'Starting {len(enabled_modules)} modules..')
    for modulename, moduleobject in active_modules.items():
        if moduleobject.enabled:
            try:
                moduleobject.matrix_start(bot)
            except Exception:
                logger.exception(f'unhandled exception from {modulename}.matrix_start')
    logger.info(f'All modules started.')


def stop(bot):
    logger.info(f'Stopping {len(active_modules)} modules..')
    for modulename, moduleobject in active_modules.items():
        try:
            moduleobject.matrix_stop(bot)
        except Exception:
            logger.exception(f'unhandled exception from {modulename}.matrix_stop')
    logger.info(f'All modules stopped.')


async def poll_timer(bot):
    while True:
        pollcount = 0
        pollcount = pollcount + 1
        for modulename, moduleobject in active_modules.items():
            if moduleobject.enabled:
                try:
                    await moduleobject.matrix_poll(bot, pollcount)
                except Exception:
                    logger.exception(f'unhandled exception from {modulename}.matrix_poll')
        await asyncio.sleep(10)


async def run(bot):
    global bot_task, poll_task, bot_instance        
    bot_instance = bot 

    data = get_account_data()
    
    if data is None:
        logger.info("Initializing account data for the first time...")
        save_settings(bot) 

    sync_response = await client.sync()
    if type(sync_response) == SyncError:
        logger.error(f"Received Sync Error when trying to do initial sync! Error message is: %s", sync_response.message)
    else:
        for roomid, room in client.rooms.items():
            # logger.info(f"Bot is on '{room.display_name}'({roomid}) with {len(room.users)} users")
            if len(room.users) == 1 and leave_empty_rooms:
                logger.info(f'Room {roomid} has no other users - leaving it.')
                logger.info(await client.room_leave(roomid))

        if client.logged_in:
            start(bot)
            poll_task = asyncio.get_event_loop().create_task(poll_timer(bot))
            load_settings(get_account_data())

 
            client.add_event_callback(functools.partial(message_cb, bot), RoomMessageText)
            client.add_event_callback(functools.partial(invite_cb, bot), (InviteEvent,))
            client.add_event_callback(functools.partial(memberevent_cb, bot), (RoomMemberEvent,))

            if join_on_invite:
                logger.info('Note: Bot will join rooms if invited')
            if len(invite_whitelist) > 0:
                logger.info(f'Note: Bot will only join rooms when the inviting user is contained in {invite_whitelist}')
            
            logger.info(f'Bot running as {client.user_id}, owners {owners}')
            bot_task = asyncio.create_task(client.sync_forever(timeout=30000))
            await bot_task
        else:
            logger.error('Client was not able to log in, check env variables!')


async def shutdown():
    await close()


async def close():
    try:
        await client.close()
        logger.info("Connection closed")
    except Exception as ex:
        logger.error("error while closing client: %s", ex)


def handle_exit(signame, loop):
    logger.info(f"Received signal {signame}")
    if poll_task:
        poll_task.cancel()
    bot_task.cancel()
    stop(bot)


