from mautrix.types import ImageInfo, MessageEvent

from ...core import loader, utils


class Meta:
    name = "HelperModule"
    _cls_doc = "Displays a list of all available commands and system information."
    version = "1.0.0"
    dependencies = ["patchlib"]
    tags = ["helper"]


@loader.tds
class HelperModule(loader.Module):
    strings = {
        "header": "<b>💠 {name}</b><br><i>{desc}</i><br><br>",
        "default_desc": "Your personal Matrix assistant",
        "modules_title": "<b>Available modules (click to expand):</b><br><br>",
        "module_item": (
            "<details>"
            "<summary>▫️ <b>{name}</b></summary>"
            "<i>{desc}</i><br>"
            "⬥ {commands}"
            "</details>"
        ),
        
        "module_info": "<b>📦 Module:</b> {name}<br><b>ℹ️ Description:</b> {desc}<br><br>",
        "config_title": "<b>⚙️ Settings (Configuration):</b><br>",
        "config_item": "    ⬥ <code>{key}</code>: <i>{desc}</i> (Current: <code>{val}</code>)<br>",
        "config_usage_hint": "<br><i>To change: <code>{prefix}cfg {name} [key] [value]</code></i><br>",
        "commands_title": "<br><b>🛠 Commands:</b><br>",
        
        "cmd_info": "<b>Command:</b> <code>{prefix}{name}</code><br><b>Description:</b> {desc}",
        "cmd_not_found": "❌ Command or module <code>{name}</code> not found.",
        "no_desc": "No description available",
        "no_cmds": "No commands",
        
        "cfg_usage": "⚠️ Usage: <code>{prefix}cfg [Module] [Key] [Value]</code>",
        "mod_not_found": "❌ Module <b>{name}</b> not found.",
        "mod_no_cfg": "❌ Module <b>{name}</b> does not support configuration.",
        "cfg_success": "✅ Setting <b>{key}</b> for module <b>{mod}</b> updated to <code>{val}</code>",
        "cfg_fail": "❌ Failed to update <b>{key}</b>. Check data type or key existence.",
        
        "info_caption": (
            "<b><u>MxUserBot Info</u></b><br>"
            "🆔 | Version: <code>{version}</code><br>"
            "👩‍💻 | Sources: "
            "<a href='https://github.com/PashaHatsune/MxUserbot'>GitHub</a><br>"
        )
    }

    @loader.command()
    async def help(self, mx, event: MessageEvent):
        """Displays a list of commands or detailed info about a module/command"""
        
        args = await utils.get_args(mx, event)
        prefix = await mx.get_prefix()

        if not args:
            msg = self.strings.get("header").format(
                name="MxUserBot",
                desc=self.strings.get("default_desc")
            )
            msg += self.strings.get("modules_title")

            # Сортируем модули по имени для удобства
            sorted_modules = sorted(
                mx.active_modules.values(), 
                key=lambda x: (x.Meta.name if hasattr(x, "Meta") else x.__class__.__name__)
            )

            for mod in sorted_modules:
                name = mod.Meta.name if hasattr(mod, "Meta") else mod.__class__.__name__
                desc = mod.Meta._cls_doc if hasattr(mod, "Meta") else self.strings.get("no_desc")
                
                if hasattr(mod, "commands") and mod.commands:
                    cmds = ", ".join([f"<code>{c}</code>" for c in mod.commands.keys()])
                else:
                    cmds = self.strings.get("no_cmds")

                msg += self.strings.get("module_item").format(
                    name=name,
                    desc=desc,
                    commands=cmds
                )
            
            return await utils.answer(mx, msg)

        target = args[0].lower()

        found_mod = None
        for mod in mx.active_modules.values():
            mod_name = (mod.Meta.name if hasattr(mod, "Meta") else mod.__class__.__name__).lower()
            if target == mod_name:
                found_mod = mod
                break

        if found_mod:
            name = found_mod.Meta.name if hasattr(found_mod, "Meta") else found_mod.__class__.__name__
            desc = found_mod.Meta._cls_doc if hasattr(found_mod, "Meta") else self.strings.get("no_desc")
            
            msg = self.strings.get("module_info").format(name=name, desc=desc)

            if hasattr(found_mod, "config") and hasattr(found_mod.config, "_schema"):
                msg += self.strings.get("config_title")
                for key, cfg_val in found_mod.config._schema.items():
                    current_val = found_mod.config[key]
                    msg += self.strings.get("config_item").format(
                        key=key,
                        desc=cfg_val.description or self.strings.get("no_desc"),
                        val=current_val
                    )
                msg += self.strings.get("config_usage_hint").format(prefix=prefix, name=name)

            if hasattr(found_mod, "commands") and found_mod.commands:
                msg += self.strings.get("commands_title")
                for cmd_name, func in found_mod.commands.items():
                    msg += f" • <code>{prefix}{cmd_name}</code> — <i>{func.__doc__ or '...'}</i><br>"
            
            return await utils.answer(mx, msg)

        for mod in mx.active_modules.values():
            if hasattr(mod, "commands") and target in mod.commands:
                func = mod.commands[target]
                doc = func.__doc__ or self.strings.get("no_desc")

                res = self.strings.get("cmd_info").format(
                    prefix=prefix,
                    name=target,
                    desc=doc
                )
                return await utils.answer(mx, res)

        await utils.answer(mx, 
            self.strings.get("cmd_not_found").format(
                name=target
            )
        )

    @loader.command()
    async def cfg(self, mx, event: MessageEvent):
        """Changes module configuration. Usage: .cfg [Module] [Key] [Value]"""
        args = await utils.get_args(mx, event)
        prefix = await mx.get_prefix()
        
        if len(args) < 3:
            return await utils.answer(mx, self.strings.get("cfg_usage").format(prefix=prefix))

        target_mod = args[0].lower()
        key = args[1]
        value = " ".join(args[2:])

        module = None
        for mod in mx.active_modules.values():
            mod_name = (mod.Meta.name if hasattr(mod, "Meta") else mod.__class__.__name__).lower()
            if target_mod == mod_name:
                module = mod
                break

        if not module:
            return await utils.answer(mx, self.strings.get("mod_not_found").format(name=target_mod))

        if not hasattr(module, "config") or not hasattr(module.config, "set"):
            return await utils.answer(mx, self.strings.get("mod_no_cfg").format(name=target_mod))

        if module.config.set(key, value):
            await utils.answer(mx, self.strings.get("cfg_success").format(
                key=key,
                mod=target_mod,
                val=value
            ))
        else:
            await utils.answer(mx, self.strings.get("cfg_fail").format(key=key))

    @loader.command()
    async def info(self, mx, event: MessageEvent):
        """Send a card with bot information"""
        await utils.send_image(
            mx=mx, 
            room_id=event.room_id,
            url="mxc://pashahatsune.pp.ua/ZPKENBwSwKgbFvrYWByGr1140eNqWQyL",
            caption=self.strings.get("info_caption").format(
                version=mx.version
            ),
            file_name="info.png",
            info=ImageInfo(width=600, height=335, mimetype="image/png")
        )