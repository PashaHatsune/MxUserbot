import os
import hashlib
from loguru import logger
from nio import RoomVisibility, RoomPreset, RoomCreateError, RoomResolveAliasResponse, RoomPutStateError

from .registry import active_modules
from .modules.core.loader import Loader
from .modules.core.room_send import room_send
from .modules.core.send_text import send_text
from .modules.core.account_settings import is_owner
from .modules.core.load_settings import load_settings 
from .modules.core.account_settings import get_account_data
from .modules.core.exceptions import CommandRequiresAdmin, CommandRequiresOwner


class Bot:
    def __init__(self):
        self.client = None
        self.modules = active_modules
        self.version = "1"
        self.uri_cache = dict()
        self.debug = os.getenv("DEBUG", "false").lower() == "true"


    def get_uri_cache(self, url, blob=False):
        """

        :param url: Url of binary content of the image to upload
        :param blob: Flag to indicate if the second param is an url or a binary content
        :return: [matrix_uri, mimetype, w, h, size], or None
        """
        cache_key = url
        if blob:  ## url is bytes, cannot be used a key for cache
            cache_key = hashlib.md5(url).hexdigest()

        return self.uri_cache.get(cache_key)


    async def send_html(self, room, html, plaintext, event=None, msgtype="m.notice", bot_ignore=False):
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
        await room_send(room.room_id, event, 'm.room.message', msg)


    async def send_location(self, room, body, latitude, longitude, event=None, bot_ignore=False, asset='m.pin'):
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
        await room_send(room.room_id, event, 'm.room.message', locationmsg)


    async def send_image(self, room, url, body, event=None, mimetype=None, width=None, height=None, size=None):
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

        return await room_send(room.room_id, event, 'm.room.message', msg)


    async def set_room_avatar(self, room, uri):
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
            await send_text(self, room, f"sorry. can't set room avatar. I need at least be a moderator")

        return result


    async def send_msg(self, mxid, roomname, message):
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
        await send_text(self, msg_room, message)
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


    # Throws exception if event sender is not a room admin
    def must_be_admin(self, room, event, power_level=50):
        if not self.is_admin(room, event, power_level=power_level):
            raise CommandRequiresAdmin


    # Throws exception if event sender is not a bot owner
    def must_be_owner(self, event):
        if not is_owner(event):
            raise CommandRequiresOwner


    # Returns true if event's sender has PL50 or more in the room event was sent in,
    # or is bot owner
    def is_admin(self, room, event, power_level=50):
        if is_owner(event):
            return True
        if event.sender not in room.power_levels.users:
            return False
        return room.power_levels.users[event.sender] >= power_level


    # Checks if this event should be ignored by bot, including custom property
    def should_ignore_event(self, event):
        return "org.vranki.hemppa.ignore" in event.source['content']


    def reload_modules(self):
        for modulename in self.modules:
            logger.info(f'Reloading {modulename} ..')
            self.modules[modulename] = Loader().register_module(modulename)

            load_settings(get_account_data())


    def clear_modules(self):
        self.modules = dict()
