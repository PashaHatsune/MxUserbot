


import re
import sys
import datetime
from loguru import logger

# from .starts_with_command import starts_with_command
from .exceptions import CommandRequiresAdmin, CommandRequiresOwner



import datetime
from loguru import logger
from nio import InviteEvent, JoinError, MatrixRoom

from ...settings import config


invite_whitelist = {}
join_on_invite = True

class CallBack:
    def __init__(self, bot):
        self.bot = bot


    async def invite_cb(self, room, event):

        room: MatrixRoom
        event: InviteEvent

        if len(invite_whitelist) > 0 and not await self.bot.on_invite_whitelist(event.sender):
            logger.error(f'Cannot join room {room.display_name}, as {event.sender} is not whitelisted for invites!')
            return

        if join_on_invite or await self.bot.is_owner(event):
            for attempt in range(3):
                self.bot.jointime = datetime.datetime.now()
                result = await self.bot.join(room.room_id)
                if type(result) == JoinError:
                    logger.error(f"Error joining room %s (attempt %d): %s", room.room_id, attempt, result.message)
                else:
                    logger.info(f"joining room '{room.display_name}'({room.room_id}) invited by '{event.sender}'")
                    return
        else:
            logger.warning(f'Received invite event, but not joining as sender is not owner or bot not configured to join on invite. {event}')

    async def memberevent_cb(
            self,
            room,
            event
    ):
        # Automatically leaves rooms where bot is alone.
        if room.member_count == 1 and event.membership=='leave' and event.sender != config.matrix_config.owner:
            logger.info(f"Membership event in {room.display_name} ({room.room_id}) with {room.member_count} members by '{event.sender}' (I am OWNER)- leaving room as i don't want to be left alone!")
            await self.bot.room_leave(room.room_id)


    async def message_cb(self, room, event):
        # Ignore if asked to ignore
        if self.bot.should_ignore_event(event):
            # logger.debug('Ignoring event!')
            return
        
        body = event.body
        
        if not self.bot.starts_with_command(body):
            return
        


        prefix = "!"
        if event.body.startswith(prefix):
            # Отрезаем префикс и делим на команду и аргументы
            parts = event.body[len(prefix):].split(None, 1)
            cmd_name = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            for mod in self.bot.all_modules.active_modules.values():
                if not mod.enabled: continue
                
                if cmd_name in mod.commands:
                    func = mod.commands[cmd_name]
                    try:
                        # Вызываем команду!
                        await func(self.bot, room, event, args)
                    except Exception as e:
                        logger.exception(f"Error in command {cmd_name}")
                        await self.bot.send_text(room, f"❌ Ошибка: {e}")
                    return # Выходим: команда найдена и обработана

        # 3. Если это не команда, вызываем Watchers (matrix_message)
        for mod in self.bot.all_modules.active_modules.values():
            if mod.enabled:
                try:
                    await mod.matrix_message(self.bot, room, event)
                except Exception:
                    logger.exception(f"Error in watcher of {mod.name}")