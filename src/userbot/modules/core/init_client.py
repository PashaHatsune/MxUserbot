import os
import sys
import asyncio
from loguru import logger
from nio import AsyncClient

from ...import registry 
from ....settings import config


_client_instance = None


def init_client():
    global _client_instance
    
    if _client_instance is not None:
        return _client_instance

    matrix_server = config.matrix_config.base_url
    bot_owner = config.matrix_config.owner
    access_token = config.matrix_config.access_token.get_secret_value()
    
    join_on_invite = os.getenv('JOIN_ON_INVITE', 'False').lower() == 'true'
    invite_whitelist = os.getenv('INVITE_WHITELIST', '').split(',')
    if invite_whitelist == ['']: invite_whitelist = []

    if matrix_server and bot_owner and access_token:
        logger.info(f"Initializing Matrix Client for {bot_owner}...")
        
        client = AsyncClient(
            matrix_server, 
            bot_owner, 
            ssl=matrix_server.startswith("https://")
        )
        client.access_token = access_token
        

        registry.join_on_invite = join_on_invite
        registry.invite_whitelist = invite_whitelist
        registry.owners = [bot_owner]

        _client_instance = client

        from .loader import Loader
        loader = Loader()
        asyncio.run(loader.register_all_modules())

        return _client_instance

    else:
        logger.error("Mandatory config missing: check MATRIX_SERVER, OWNER, and ACCESS_TOKEN")
        sys.exit(1)