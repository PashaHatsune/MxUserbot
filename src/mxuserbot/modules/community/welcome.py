import asyncio
from typing import Any
from mautrix.types import MessageEvent, EventType, Membership, StateEvent
from loguru import logger
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "WelcomeModule",
        "_cls_doc": "Кастомные приветствия для каждого чата",
        "welcome_msg": "👋 Привет, {displayname}! Добро пожаловать в <b>{room}</b>!",
        "leave_msg": "🚪 {displayname} покинул нас...",
        "status_on": "<b>[Welcome]</b> ✅ Приветствия включены.",
        "status_off": "<b>[Welcome]</b> ❌ Приветствия выключены.",
        "text_saved": "<b>[Welcome]</b> ✅ Текст сохранен!"
    }

    async def _get_settings(self) -> dict:
        settings = await self._get("room_settings", {})
        return settings if isinstance(settings, dict) else {}

    def _format_text(self, text: str, event: StateEvent, room_name: str) -> str:
        user_id = str(event.state_key)
        displayname = event.content.displayname or user_id
        
        mention = f'<a href="https://matrix.to/#/{user_id}">{displayname}</a>'
        
        return text.replace("{user}", mention) \
                .replace("{room}", room_name) \
                .replace("{displayname}", displayname) \
                .replace("{username}", user_id.split(":")[0].replace("@", ""))
    

    async def _matrix_member(self, mx: Any, event: StateEvent):
        """Обработчик событий членства"""
        room_id = str(event.room_id)
        target_user = event.state_key
        # ВАЖНО: Доступ к membership через .content
        membership = event.content.membership 


        if target_user == mx.client.mxid:
            return

        settings = await self._get_settings()
        
        if room_id not in settings:
            return

        room_config = settings[room_id]
        
        room_name = "этот чат"
        try:
            name_event = await mx.client.get_state_event(room_id, EventType.ROOM_NAME)
            if name_event and name_event.name:
                room_name = name_event.name
        except Exception:
            pass

        if membership == Membership.JOIN:
            logger.info(f"[Welcome] Отправляю приветствие для {target_user}")
            raw_text = room_config.get("welcome_text", self.strings["welcome_msg"])
            await asyncio.sleep(1)
            formatted = self._format_text(raw_text, event, room_name)
            await mx.client.send_text(room_id, html=formatted)

        elif membership == Membership.LEAVE:
            logger.info(f"[Welcome] Отправляю прощание для {target_user}")
            raw_text = room_config.get("leave_text", self.strings["leave_msg"])
            await asyncio.sleep(0.5)
            formatted = self._format_text(raw_text, event, room_name)
            await mx.client.send_text(room_id, html=formatted)

    @loader.command()
    async def welcomecfg(self, mx: Any, event: MessageEvent):
        """Включить/выключить приветствия"""
        room_id = str(event.room_id)
        settings = await self._get_settings()

        if room_id in settings:
            del settings[room_id]
            msg = self.strings["status_off"]
        else:
            settings[room_id] = {}
            msg = self.strings["status_on"]

        await self._set("room_settings", settings)
        await mx.client.send_text(room_id, html=msg)

    @loader.command()
    async def setwelcome(self, mx: Any, event: MessageEvent):
        """Установить текст приветствия"""
        args = event.content.body.split(maxsplit=1)
        if len(args) < 2:
            return await mx.client.send_text(event.room_id, "Введите текст!")

        settings = await self._get_settings()
        room_id = str(event.room_id)
        if room_id not in settings: settings[room_id] = {}
        
        settings[room_id]["welcome_text"] = args[1]
        await self._set("room_settings", settings)
        await mx.client.send_text(room_id, html=self.strings["text_saved"])