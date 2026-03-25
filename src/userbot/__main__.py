import sys
import signal
import asyncio
import traceback
from loguru import logger
from nio import AsyncClient, ClientConfig

from .core.bot import Bot
from ..database.methods import Database
# ТЕБЕ НУЖНО ИМПОРТИРОВАТЬ ЭТО (название класса может отличаться)
from ..database import AsyncSessionWrapper  
from ..settings import config

import functools

async def main():
    # 1. Инициализация обертки сессий (движка алхимии)
    sw = AsyncSessionWrapper() 
    
    # 2. Передаем sw в Database
    db = Database(sw) 


    url = config.matrix_config.base_url
    

    conf = ClientConfig(store_sync_tokens=True)
    # 3. Настройка клиента Matrix
    client = AsyncClient(
        config.matrix_config.base_url, 
        config.matrix_config.owner,
        ssl=url.startswith("https://"),
        config=conf, store_path="store.db"
        
    )
    client.access_token = config.matrix_config.access_token.get_secret_value()

    # 4. Создание бота
    bot = Bot(db, client)


    loop = asyncio.get_running_loop()

    for signame in {'SIGINT', 'SIGTERM'}:
        loop.add_signal_handler(
            getattr(signal, signame),
            functools.partial(bot.handle_exit, signame, loop))

    try:
        await bot.run()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.error("Global crash:")
        traceback.print_exc()
    finally:
        await bot.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        traceback.print_exc(file=sys.stderr)