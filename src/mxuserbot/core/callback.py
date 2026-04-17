from typing import TYPE_CHECKING
from loguru import logger

from mautrix.types import (
    StateEvent, 
    MessageEvent, 
    Membership, 
    EventType
)

if TYPE_CHECKING:
    from ..__main__ import MXUserBot


invite_whitelist = {}
join_on_invite = True


class CallBack:
    def __init__(self, mx: 'MXUserBot'):
        self.mx = mx

    async def invite_cb(self, evt: StateEvent):
        """Обработка инвайтов"""
        if self.mx.start_time and evt.timestamp < self.mx.start_time:
            return

        if evt.type != EventType.ROOM_MEMBER or evt.content.membership != Membership.INVITE:
            return

        if evt.state_key != self.mx.client.mxid:
            return

        sender = evt.sender
        room_id = evt.room_id
        via_server = sender.split(":")[-1]

        if join_on_invite or await self.mx.is_owner(evt):
            try:
                await self.mx.client.join_room(room_id, servers=[via_server])
                logger.info(f"Joined room '{room_id}' invited by '{sender}'")
            except Exception as e:
                logger.error(f"Error joining room {room_id}: {e}")

    async def memberevent_cb(self, evt: StateEvent):
        """Обработка событий членства (Join/Leave/Invite)"""
        if self.mx.start_time and evt.timestamp < self.mx.start_time:
            return

        if evt.type != EventType.ROOM_MEMBER:
            return
            
        content = evt.content
        room_id = evt.room_id
        target_user = evt.state_key 

        for mod in self.mx.active_modules.values():
            if mod.enabled and getattr(mod, "_is_ready", False):
                try:
                    if hasattr(mod, "_matrix_member"):
                        await mod._matrix_member(self.mx, evt)
                except Exception:
                    logger.exception(f"Error in _matrix_member in {mod.name}")

        if target_user == self.mx.client.mxid:
            return

        if content.membership == Membership.LEAVE:
            try:
                members = await self.mx.client.get_joined_members(room_id)
                if len(members) == 1:
                    logger.info(f"Leaving {room_id} as I am left alone!")
                    await self.mx.client.leave_room(room_id)
            except Exception as e:
                logger.warning(f"Failed to check member count in {room_id}: {e}")


    async def message_cb(self, evt: MessageEvent):
        """Обработка сообщений (аналог RoomMessage)"""
        if self.mx.start_time and evt.timestamp < self.mx.start_time:
            return

        body = evt.content.body
        if not body:
            return

        if self.mx.should_ignore_event(evt):
            return

        real_body = body.strip()

        if not await self.mx.starts_with_command(real_body):
            for mod in self.mx.active_modules.values():
                if mod.enabled and getattr(mod, "_is_ready", False):
                    try:
                        await mod._matrix_message(self.mx.interface, evt)
                    except Exception:
                        logger.exception(f"Error in watcher in {mod.name}")
            return

        used_prefix = None
        for p in await self.mx.get_prefix():
            if real_body.startswith(p):
                used_prefix = p
                break

        if used_prefix:
            cmd_part = real_body[len(used_prefix):]
            parts = cmd_part.split(None, 1)
            if not parts:
                return
                
            cmd_name = parts[0].lower()

            for mod in self.mx.active_modules.values():
                if not mod.enabled:
                    continue
                
                if cmd_name in mod.commands:
                    if not getattr(mod, "_is_ready", True):
                        return 
                        
                    func = mod.commands[cmd_name]
                    try:
                        if not self.mx.interface.is_owner(evt.sender):
                            return
                        
                        token = self.mx.interface._current_event.set(evt)
                        try:
                            await func(self.mx.interface, evt)
                        except Exception:
                            logger.exception(f"Error in command {cmd_name}")
                        finally:
                            self.mx.interface._current_event.reset(token)
                        

                    except Exception as e:
                        logger.exception(f"Error in command {cmd_name}")
                        await self.mx.client.send_text(evt.room_id, f"❌ Ошибка: {e}")
                    return