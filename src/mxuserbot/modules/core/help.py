from ...core import loader
from mautrix.types import MessageEvent
from typing import Any # Для правильной типизации mx, если не хочешь импортировать MXUserBot

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "HelperModule",
        "_cls_doc": "Отображает список всех доступных команд и информацию о модулях.",
        "header": "<b>💠 {name}</b>\n<i>{desc}</i>\n\n",
        "modules_title": "<b>Доступные модули и команды:</b>\n",
        "module_item": "▫️ <b>{name}</b> — <i>{desc}</i>\n    ⬥ {commands}\n\n",
        "cmd_info": "<b>Команда:</b> <code>{prefix}{name}</code>\n<b>Описание:</b> {desc}",
        "cmd_not_found": "❌ Команда <code>{prefix}{name}</code> не найдена.",
        "no_desc": "Описание отсутствует",
        "no_cmds": "Нет команд"
    }

    @loader.command()
    async def help(self, mx: Any, event: MessageEvent):
        """Отображает список команд"""
        
        # В mautrix текст сообщения всегда в event.content.body
        if not event.content.body:
            return
            
        parts = event.content.body.split()
        args = parts[1] if len(parts) > 1 else None
        
        # Берем префикс из твоего MXUserBot
        prefix = mx.prefixes[0]

        if not args:
            msg = self.strings["header"].format(
                name=self.friendly_name, 
                desc=self._help()
            )
            msg += self.strings["modules_title"]
            
            for mod in mx.active_modules.values():
                if mod.commands:
                    cmds = ", ".join([f"<code>{prefix}{c}</code>" for c in mod.commands.keys()])
                else:
                    cmds = self.strings["no_cmds"]

                msg += self.strings["module_item"].format(
                    name=mod.friendly_name, 
                    desc=mod._help(),
                    commands=cmds
                )

            # Используем html=msg, чтобы mautrix правильно обработал теги
            # event.room_id вместо event.room
            return await mx.client.send_text(
                room_id=event.room_id, 
                html=msg
            )

        cmd_name = args.lower()
        for mod in mx.active_modules.values():
            if cmd_name in mod.commands:
                func = mod.commands[cmd_name]
                doc = mod.strings.get(f"_cmd_doc_{cmd_name}") or func.__doc__ or self.strings["no_desc"]
                
                res = self.strings["cmd_info"].format(
                    prefix=prefix,
                    name=cmd_name,
                    desc=doc
                )
                return await mx.client.send_text(event.room_id, html=res)
        
        await mx.client.send_text(
            event.room_id, 
            html=self.strings["cmd_not_found"].format(
                prefix=prefix,
                name=cmd_name
            )
        )