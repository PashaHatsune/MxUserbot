import sys
import signal
import asyncio
import functools
import traceback

from .bot import Bot
from . import handle_exit, run, shutdown
from .modules.core.init_client import init_client


async def main():
    bot = Bot()
    init_client()

    loop = asyncio.get_running_loop()

    for signame in {'SIGINT', 'SIGTERM'}:
        loop.add_signal_handler(
            getattr(signal, signame),
            functools.partial(handle_exit, signame, loop))

    await run(bot)
    await shutdown()


try:
    asyncio.run(main())
except Exception as e:
    traceback.print_exc(file=sys.stderr)
