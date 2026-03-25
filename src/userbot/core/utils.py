
# import re




def get_commands(cls):
    cmds = {}
    for attr_name in dir(cls):
        method = getattr(cls, attr_name)
        if callable(method) and getattr(method, 'is_command', False):
            cmds[method.command_name] = method
    return cmds

# def is_owner(event):
#     return event.sender in owners



# from loguru import logger








# # Throws exception if event sender is not a room admin
# def must_be_admin(self, room, event, power_level=50):
#     if not self.is_admin(room, event, power_level=power_level):
#         raise CommandRequiresAdmin


# # Throws exception if event sender is not a bot owner
# def must_be_owner(self, event):
#     if not is_owner(event):
#         raise CommandRequiresOwner


# # Returns true if event's sender has PL50 or more in the room event was sent in,
# # or is bot owner
# def is_admin(self, room, event, power_level=50):
#     if is_owner(event):
#         return True
#     if event.sender not in room.power_levels.users:
#         return False
#     return room.power_levels.users[event.sender] >= power_level


# # Checks if this event should be ignored by bot, including custom property
# def should_ignore_event(self, event):
#     return "org.vranki.hemppa.ignore" in event.source['content']





# def clear_modules(self):
#     self.modules = dict()
