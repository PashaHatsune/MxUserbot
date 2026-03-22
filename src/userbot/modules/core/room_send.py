# Wrapper around matrix-nio's client.room_send
# Use src_event context to modify the msg

from loguru import logger
from .init_client import init_client

client = init_client()

async def room_send(
        room_id,
        pre_event,
        msgtype,
        msg,
        **kwargs
):
    if pre_event is None:
        logger.info(f'No pre-event passed. This module may not be set up to support m.thread.')
    try:
        # m.thread support
        relates_to = pre_event.source['content']['m.relates_to']
        if relates_to['rel_type'] == 'm.thread':
            msg['m.relates_to'] = relates_to
            msg['m.relates_to']['m.in_reply_to'] = {'event_id': pre_event.event_id}
    except (AttributeError, KeyError):
        pass

    return await client.room_send(room_id, msgtype, msg, **kwargs)