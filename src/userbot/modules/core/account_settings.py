import json
import urllib
import requests
from loguru import logger

from ...registry import owners
from ....settings import config
from .init_client import init_client
from .exceptions import handle_error_response


client = init_client()


def set_account_data(data):
    userid = urllib.parse.quote(config.matrix_config.owner)

    headers = {
        'Authorization': f'Bearer {config.matrix_config.access_token.get_secret_value()}',
    }
    ad_url = f"{client.homeserver}/_matrix/client/v3/user/{userid}/account_data/{config.matrix_config.appid}"
    response = requests.put(ad_url, json.dumps(data), headers=headers)
    handle_error_response(response)
    
    logger.debug(f"респонс от сета аккаунта: {response}")

    if response.status_code == 200:
        return response.json()
    logger.error(f'Getting account data failed: {response} {response.json()} - this is normal if you have not saved any settings yet.')
    return None


def get_account_data():
    userid = urllib.parse.quote(config.matrix_config.owner)
    headers = {
        'Authorization': f'Bearer {client.access_token}',
    }

    ad_url = f"{client.homeserver}/_matrix/client/v3/user/{userid}/account_data/{config.matrix_config.appid}"
    response = requests.get(ad_url, headers=headers)
    handle_error_response(response)

    if response.status_code == 200:
        return response.json()
    logger.error(f'Getting account data failed: {response} {response.json()} - this is normal if you have not saved any settings yet.')
    return None


# Returns true if event's sender is owner of the bot
def is_owner(event):
    return event.sender in owners