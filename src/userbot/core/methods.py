    



from loguru import logger


import json
import urllib
import requests
from loguru import logger

from ...settings import config
from .exceptions import handle_error_response


import hashlib

from nio import (
    RoomPutStateError,
    RoomCreateError,
    RoomVisibility,
    RoomPreset,
    RoomResolveAliasResponse
)

class Methods:
    def __init__(self, bot):
        self.bot = bot

    async def get_uri_cache(
            self,
            url,
            blob=False
    ) -> dict:
            """

            :param url: Url of binary content of the image to upload
            :param blob: Flag to indicate if the second param is an url or a binary content
            :return: [matrix_uri, mimetype, w, h, size], or None
            """
            cache_key = url
            if blob:  ## url is bytes, cannot be used a key for cache
                cache_key = hashlib.md5(url).hexdigest()

            return self.uri_cache.get(cache_key)


    async def send_html(
            self,
            room,
            html,
            plaintext,
            event=None,
            msgtype="m.notice",
            bot_ignore=False
    ):
        """

        :param room: A MatrixRoom the html should be send to
        :param html: Html content of the message
        :param plaintext: Plaintext content of the message
        :param msgtype: The message type for the room https://matrix.org/docs/spec/client_server/latest#m-room-message-msgtypes
        :param bot_ignore: Flag to mark the message to be ignored by the bot
        :return:
        """

        msg = {
            "msgtype": msgtype,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
            "body": plaintext
        }
        if bot_ignore:
            msg["org.vranki.hemppa.ignore"] = "true"
        await self.room_send(room.room_id, event, 'm.room.message', msg)


    async def send_location(
            self,
            room,
            body,
            latitude,
            longitude,
            event=None,
            bot_ignore=False,
            asset='m.pin'
    ):
        """

        :param room: A MatrixRoom the html should be send to
        :param html: Html content of the message
        :param body: Plaintext content of the message
        :param latitude: Latitude in WGS84 coordinates (float)
        :param longitude: Longitude in WGS84 coordinates (float)
        :param bot_ignore: Flag to mark the message to be ignored by the bot
        :param asset: Asset string as defined in MSC3488 (such as m.self or m.pin)
        :return:
        """
        locationmsg = {
            "body": str(body),
            "geo_uri": 'geo:' + str(latitude) + ',' + str(longitude),
            "msgtype": "m.location",
            "org.matrix.msc3488.asset": { "type": asset }
            }
        await self.room_send(room.room_id, event, 'm.room.message', locationmsg)


    async def send_image(
            self,
            room,
            url,
            body,
            event=None,
            mimetype=None,
            width=None,
            height=None,
            size=None
    ):
        """

        :param room: A MatrixRoom the image should be send to
        :param url: A MXC-Uri https://matrix.org/docs/spec/client_server/r0.6.0#mxc-uri
        :param body: A textual representation of the image
        :param mimetype: The mimetype of the image
        :param width: Width in pixel of the image
        :param height: Height in pixel of the image
        :param size: Size in bytes of the image
        :return:
        """
        msg = {
            "url": url,
            "body": body,
            "msgtype": "m.image",
            "info": {
                "thumbnail_info": None,
                "thumbnail_url": url,
            },
        }

        if mimetype:
            msg["info"]["mimetype"] = mimetype
        if width:
            msg["info"]["w"] = width
        if height:
            msg["info"]["h"] = height
        if size:
            msg["info"]["size"] = size

        logger.debug(f"send image room message: {msg}")

        return await self.room_send(room.room_id, event, 'm.room.message', msg)

    async def send_text(
            self,
            room,
            body,
            event=None,
            msgtype="m.notice",
            bot_ignore=False
    ):
        """
        Универсальный метод отправки. 
        Если находит HTML-теги, автоматически делегирует отправку в send_html.
        """

        import re
        if bool(re.search(r'<[^>]+>', str(body))):
            plaintext = re.sub(r'<[^>]+>', '', str(body))
            

            html_body = str(body).replace("\n", "<br>")
            return await self.send_html(
                room=room,
                html=html_body,
                plaintext=plaintext,
                event=event,
                msgtype=msgtype,
                bot_ignore=bot_ignore
            )

        msg = {
            "body": body,
            "msgtype": msgtype,
        }
        if bot_ignore:
            msg["org.vranki.hemppa.ignore"] = "true"

        return await self.room_send(room.room_id, event, 'm.room.message', msg)


    async def room_send(self, room_id, pre_event, msgtype, msg, **kwargs):
        if pre_event is None:
            logger.info(f'No pre-event passed. This module may not be set up to support m.thread.')
        else:
            # m.thread support
            try:
                relates_to = pre_event.source['content']['m.relates_to']
                if relates_to['rel_type'] == 'm.thread':
                    msg['m.relates_to'] = relates_to
                    msg['m.relates_to']['m.in_reply_to'] = {'event_id': pre_event.event_id}
            except (AttributeError, KeyError):
                pass

        return await self.client.room_send(
            room_id=room_id,
            message_type=msgtype,
            content=msg,
            **kwargs
    )

    async def set_room_avatar(
            self,
            room,
            uri
    ):
        """

        :param room: A MatrixRoom the image should be send as room avatar event
        :param uri: A MXC-Uri https://matrix.org/docs/spec/client_server/r0.6.0#mxc-uri
        :return:
        """
        msg = {
            "url": uri
        }

        result = await self.client.room_put_state(room.room_id, 'm.room.avatar', msg)

        if isinstance(result, RoomPutStateError):
            logger.warning(f"can't set room avatar. {result.message}")
            await self.send_text(room, f"sorry. can't set room avatar. I need at least be a moderator")

        return result


    async def send_msg(
            self,
            mxid,
            roomname,
            message
    ):
        """

        :param mxid: A Matrix user id to send the message to
        :param roomname: A Matrix room id to send the message to
        :param message: Text to be sent as message
        :return bool: Success upon sending the message
        """
        # Sends private message to user. Returns true on success.
        msg_room = await self.find_or_create_private_msg(mxid, roomname)
        if not msg_room or (type(msg_room) is RoomCreateError):
            logger.error(f'Unable to create room when trying to message {mxid}')
            return False

        # Send message to the room
        await self.send_text(msg_room, message)
        return True


    async def find_or_create_private_msg(self, mxid, roomname):
        # Find if we already have a common room with user:
        msg_room = None
        for croomid in self.client.rooms:
            roomobj = self.client.rooms[croomid]
            if len(roomobj.users) == 2:
                for user in roomobj.users:
                    if user == mxid:
                        msg_room = roomobj

        # Nope, let's create one
        if not msg_room:
            msg_room = await self.client.room_create(visibility=RoomVisibility.private,
                name=roomname,
                is_direct=True,
                preset=RoomPreset.private_chat,
                invite={mxid},
            )
        return msg_room




    def set_account_data(self, data):
        userid = urllib.parse.quote(config.matrix_config.owner)

        headers = {
            'Authorization': f'Bearer {config.matrix_config.access_token.get_secret_value()}',
        }
        ad_url = f"{self.bot.client.homeserver}/_matrix/client/v3/user/{userid}/account_data/{config.matrix_config.appid}"
        response = requests.put(ad_url, json.dumps(data), headers=headers)
        handle_error_response(response)
        
        logger.debug(f"респонс от сета аккаунта: {response}")

        if response.status_code == 200:
            return response.json()
        logger.error(f'Getting account data failed: {response} {response.json()} - this is normal if you have not saved any settings yet.')
        return None


    def get_account_data(self):
        userid = urllib.parse.quote(config.matrix_config.owner)

        headers = {
            'Authorization': f'Bearer {self.client.access_token}',
        }

        ad_url = f"{self.client.homeserver}/_matrix/client/v3/user/{userid}/account_data/{config.matrix_config.appid}"
        response = requests.get(ad_url, headers=headers)
        handle_error_response(response)

        if response.status_code == 200:
            return response.json()
        logger.error(f'Getting account data failed: {response} {response.json()} - this is normal if you have not saved any settings yet.')
        return None


    async def on_invite_whitelist(bot, sender):
        invite_whitelist = await bot.db.get("core", "invite_whitelist", [])

        for entry in invite_whitelist:
            if entry == sender:
                return True 
            controll_value = entry.split(':')
            if controll_value[0] == '@*' and controll_value[1] == sender.split(':')[1]:
                return True
        return False
    

    def remove_callback(self, callback):
        for cb_object in self.client.event_callbacks:
            if cb_object.func == callback:
                logger.info("remove callback")
                self.client.event_callbacks.remove(cb_object)


    def get_room_by_id(self, room_id):
        try:
            return self.client.rooms[room_id]
        except KeyError:
            return None

    async def get_room_by_alias(self, alias):
        rar = await self.client.room_resolve_alias(alias)
        if type(rar) is RoomResolveAliasResponse:
            return rar.room_id
        return None
    

    
__all__ = [
    Methods
]