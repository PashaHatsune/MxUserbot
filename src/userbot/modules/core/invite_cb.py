

import datetime
from loguru import logger
from nio import InviteEvent, JoinError, MatrixRoom

from ....settings import config
from .account_settings import is_owner
from .init_client import init_client
from .starts_with_command import on_invite_whitelist
from ...registry import invite_whitelist, join_on_invite


client = init_client()


async def invite_cb(room, event):
    room: MatrixRoom
    event: InviteEvent

    if len(invite_whitelist) > 0 and not on_invite_whitelist(event.sender):
        logger.error(f'Cannot join room {room.display_name}, as {event.sender} is not whitelisted for invites!')
        return

    if join_on_invite or is_owner(event):
        for attempt in range(3):
            jointime = datetime.datetime.now()
            result = await client.join(room.room_id)
            if type(result) == JoinError:
                logger.error(f"Error joining room %s (attempt %d): %s", room.room_id, attempt, result.message)
            else:
                logger.info(f"joining room '{room.display_name}'({room.room_id}) invited by '{event.sender}'")
                return
    else:
        logger.warning(f'Received invite event, but not joining as sender is not owner or bot not configured to join on invite. {event}')

async def memberevent_cb(room, event):
    # Automatically leaves rooms where bot is alone.
    if room.member_count == 1 and event.membership=='leave' and event.sender != config.matrix_config.owner:
        logger.info(f"Membership event in {room.display_name} ({room.room_id}) with {room.member_count} members by '{event.sender}' (I am OWNER)- leaving room as i don't want to be left alone!")
        await client.room_leave(room.room_id)

