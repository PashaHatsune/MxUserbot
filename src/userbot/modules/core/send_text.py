from .room_send import room_send


async def send_text(
        bot,
        room,
        body,
        event=None,
        msgtype="m.notice",
        bot_ignore=False
):
    """

    :param room: A MatrixRoom the text should be send to
    :param body: Textual content of the message
    :param msgtype: The message type for the room https://matrix.org/docs/spec/client_server/latest#m-room-message-msgtypes
    :param bot_ignore: Flag to mark the message to be ignored by the bot
    :return: the NIO Response from room_send()
    """

    msg = {
        "body": body,
        "msgtype": msgtype,
    }
    if bot_ignore:
        msg["org.vranki.hemppa.ignore"] = "true"

    return await room_send(room.room_id, event, 'm.room.message', msg)