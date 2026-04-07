import sys
from functools import wraps
from loguru import logger

class SekaiSecurity:
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.owners = set()

    async def init_security(self):
        """Инициализация с гарантированным владельцем"""

        my_id = None
        resp = await self.bot.client.whoami()
        if hasattr(resp, "user_id"):
            my_id = resp.user_id


        if not my_id:
            logger.critical("CANNOT DETERMINE OWNER ID! Shutting down for security reasons.")
            sys.exit(1)

        self.owners.add(my_id)

        raw_data = await self.db.get("core", "owners")
        
        db_owners = []
        if hasattr(raw_data, 'value'):
            db_owners = raw_data.value
        elif isinstance(raw_data, list):
            db_owners = raw_data

        if isinstance(db_owners, list):
            for owner in db_owners:
                if owner and isinstance(owner, str):
                    self.owners.add(owner)

        await self.db.set("core", "owners", list(self.owners))
        logger.success(f"Security active. Owners: {self.owners}")


    def is_owner(self, sender_id: str) -> bool:
        return sender_id in self.owners


    def gate(self, func):
        """
        Автоматический защитник. 
        Оборачивает колбэк и не пускает его дальше, если отправитель не овнер.
        """
        @wraps(func)
        async def wrapper(event):
            sender = getattr(event, "sender", None)
            
            if not sender:
                return await func(event)

            if self.is_owner(sender):
                return await func(event)
            
            #logger.debug(f"Security: Blocked event from {sender}")
            return 

        return wrapper