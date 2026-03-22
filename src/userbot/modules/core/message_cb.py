


import re
import sys
import datetime
from loguru import logger

from .send_text import send_text
from .starts_with_command import starts_with_command
from .exceptions import CommandRequiresAdmin, CommandRequiresOwner
from ...registry import active_modules, join_hack_time, module_aliases


async def message_cb(bot, room, event):
    # Ignore if asked to ignore
    # if should_ignore_event(event):
    #     if debug:
    #         logger.debug('Ignoring event!')
    #     return

    body = event.body
    # Figure out the command
    if not starts_with_command(body):
        return

    # if owners_only and not is_owner(event):
    #     logger.info(f"Ignoring {event.sender}, because they're not an owner")
    #     await send_text(room, "Sorry, only bot owner can run commands.", event=event)
    #     return
    jointime = None

    # HACK to ignore messages for some time after joining.
    if jointime:
        if (datetime.datetime.now() - jointime).seconds < join_hack_time:
            logger.info(f"Waiting for join delay, ignoring message: {body}")
            return
        jointime = None

    command = body.split().pop(0)

    # Strip away non-alphanumeric characters, including leading ! for security
    command = re.sub(r'\W+', '', command)

    # Fallback to any declared aliases
    moduleobject = active_modules.get(command) or active_modules.get(module_aliases.get(command))

    if moduleobject is not None:
        if moduleobject.enabled:
            try:
                await moduleobject.matrix_message(bot, room, event)
            except CommandRequiresAdmin:
                await send_text(bot, room, f'Sorry, you need admin power level in this room to run that command.', event=event)
            except CommandRequiresOwner:
                await send_text(bot, room, f'Sorry, only bot owner can run that command.', event=event)
            except Exception:
                await send_text(bot, room, f'Module {command} experienced difficulty: {sys.exc_info()[0]} - see log for details', event=event)
                logger.exception(f'unhandled exception in !{command}')
    else:
        logger.error(f"Unknown command: {command}")
        # TODO Make this configurable
        # await send_text(room,
        #                     f"Sorry. I don't know what to do. Execute !help to get a list of available commands.")
