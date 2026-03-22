

import re

from ...registry import invite_whitelist


def starts_with_command(body):
    """Checks if body starts with ! and has one or more letters after it"""
    return re.match(r"^!\w.*", body) is not None


def on_invite_whitelist(sender):
    for entry in invite_whitelist:
        if entry == sender:
            return True 
        controll_value = entry.split(':')
        if controll_value[0] == '@*' and controll_value[1] == sender.split(':')[1]:
            return True
    return False