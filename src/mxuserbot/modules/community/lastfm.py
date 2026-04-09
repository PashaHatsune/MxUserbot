import aiohttp
import asyncio
import json
import os
from mautrix.types import MessageEvent
from ...core import loader
from ...core import utils

@loader.tds
class MatrixModule(loader.Module):
    """Модуль для трансляции текущего трека из LastFM (Now Playing)"""
    
    strings = {
        "name": "LastFM",
        "_cls_doc": "Отображение текущей музыки из LastFM",
        "no_username": "<b>[LastFM]</b> Имя пользователя не настроено. Используй <code>.lfconfig &lt;username&gt;</code>",
        "config_saved": "<b>[LastFM]</b> Никнейм <code>{}</code> успешно сохранен!",
        "now_playing": "🎶 <b>Now playing:</b> <code>{}</code>",
        "not_playing": "<b>[LastFM]</b> Сейчас ничего не играет.",
        "auto_started": "<b>[LastFM]</b> Автообновление статуса запущено в этом сообщении!",
        "auto_stopped": "<b>[LastFM]</b> Автообновление остановлено.",
        "error": "<b>[LastFM]</b> Ошибка: <code>{}</code>"
    }

    API_KEY = "460cda35be2fbf4f28e8ea7a38580730"
    CONFIG_FILE = "lastfm_config.json"

    def __init__(self):
        self.configg = {}
        self.bg_task = None
        self.load_config()
        self.username = "MikuSv0"

    def load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.configg = json.load(f)
            except Exception:
                self.configg = {}
        else:
            self.configg = {}

    def save_config(self):
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.configg, f, ensure_ascii=False, indent=4)

    async def get_current_song(self) -> dict: # Изменили тип возвращаемого значения на dict
            username = self.username
            if not username:
                return None

            url = f"http://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={username}&api_key={self.API_KEY}&format=json&limit=1"
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            print(data)
                            tracks = data.get("recenttracks", {}).get("track", [])
                            
                            if tracks:
                                track = tracks[0]
                                is_playing = "@attr" in track and track["@attr"].get("nowplaying") == "true"
                                
                                if is_playing:
                                    artist = track.get("artist", {}).get("#text", "Unknown Artist")
                                    name = track.get("name", "Unknown Track")
                                    album = track.get("album", {}).get("#text", "Unknown Album")

                                    images = track.get("image", [])
                                    cover_url = images[-1].get("#text") if images else None

                                    return {
                                        "text": f"{artist} — {name}",
                                        "image": cover_url,
                                        "artist": artist,
                                        "track": name,
                                        "album": album
                                    }

                return None
            except Exception as e:
                print(f"Error: {e}")
                return None

    @loader.command()
    async def lfconfig(self, mx, event: MessageEvent):
        """<username> - Установить LastFM никнейм"""
        args = utils.get_args_raw(event.content.body)
        if not args:
            return await mx.client.send_text(event.room_id, "Использование: <code>.lfconfig username</code>", html=True)

        username = args.strip()
        self.configg["username"] = username
        self.save_config()
        
        await mx.client.send_text(event.room_id, self.strings["config_saved"].format(utils.escape_html(username)), html=True)

    @loader.command()
    async def np(self, mx, event: MessageEvent):
        """Узнать текущий играющий трек"""
        if not self.username:
            return await mx.client.send_text(event.room_id, self.strings["no_username"], html=True)

        song = await self.get_current_song()
        if song and song != "Nothing Currently Playing":
            text = self.strings["now_playing"].format(utils.escape_html(song))
        else:
            text = self.strings["not_playing"]
            
        await mx.client.send_text(event.room_id, text, html=True)

    @loader.command()
    async def lfauto(self, mx, event: MessageEvent):
        """Запустить автообновление играющего трека в текущем сообщении"""
        if not self.username:
            return await mx.client.send_text(event.room_id, self.strings["no_username"], html=True)

        if self.bg_task and not self.bg_task.done():
            self.bg_task.cancel()

        initial_text = self.strings["auto_started"]
        evt_id = await mx.client.send_text(event.room_id, initial_text, html=True)
        
        self.configg["room_id"] = event.room_id
        self.configg["event_id"] = evt_id
        self.save_config()

        self.bg_task = asyncio.create_task(self._auto_update_loop(mx))

    @loader.command()
    async def lfstop(self, mx, event: MessageEvent):
        """Остановить автообновление"""
        if self.bg_task and not self.bg_task.done():
            self.bg_task.cancel()
            self.bg_task = None
            
        self.configg.pop("room_id", None)
        self.configg.pop("event_id", None)
        self.save_config()
        
        await mx.client.send_text(event.room_id, self.strings["auto_stopped"], html=True)



    async def upload_cover(self, mx, url: str) -> str | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return None

                    file_bytes = await resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")

            mxc = await mx.client.upload_media(
                file_bytes,
                mime_type=content_type,
                filename="cover.jpg"
            )

            return mxc

        except Exception as e:
            print(f"[upload_cover] error: {e}")
            return None
    
    async def _auto_update_loop(self, mx):
        last_song = None

        while True:
            try:
                current_song = await self.get_current_song()
                print(current_song)

                cover_mxc = None

                if current_song and current_song.get("image"):
                    cover_mxc = await self.upload_cover(mx, current_song["image"])

                if current_song != last_song:
                    last_song = current_song

                    if current_song:
                        await mx.client.set_rpc_media(
                            artist=current_song["artist"],
                            album = current_song["album"],
                            track=current_song["track"],
                            cover_art=cover_mxc or "mxc://pashahatsune.pp.ua/Pog8OuodZbmX73kEHCO1V77VDh6ctM8e",
                            player="Last.fm"
                        )
                    else:
                        await mx.client.set_rpc_activity(
                            name="Ничего не играет",
                            details="idle"
                        )

                await asyncio.sleep(15)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[LastFM] Ошибка в цикле автообновления: {e}")

                await asyncio.sleep(15)

    async def on_load(self, mx):
        if self.configg.get("room_id") and self.configg.get("event_id"):
            self.bg_task = asyncio.create_task(self._auto_update_loop(mx))