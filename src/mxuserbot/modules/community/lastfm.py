import aiohttp
import asyncio
import os
import tempfile
from mautrix.types import MessageEvent

from ...core import loader
from ...core import utils

@loader.tds
class MatrixModule(loader.Module):
    """Модуль для трансляции текущего трека из LastFM (Now Playing)"""
    
    strings = {
        "name": "LastFM",
        "_cls_doc": "Отображение текущей музыки из LastFM",
        "no_args": "Использование: <code>.lfconfig username</code>",
        "no_username": "<b>[LastFM]</b> Имя пользователя не настроено. Используй <code>.lfconfig &lt;username&gt;</code>",
        "config_saved": "<b>[LastFM]</b> Никнейм <code>{}</code> успешно сохранен!",
        "now_playing": "🎶 <b>Now playing:</b> <code>{}</code>",
        "not_playing": "<b>[LastFM]</b> Сейчас ничего не играет.",
        "auto_started": "<b><u>[LastFM]</u></b> Автообновление статуса запущено!",
        "auto_stopped": "<b>[LastFM]</b> Автообновление остановлено.",
        "error": "<b>[LastFM]</b> Ошибка: <code>{}</code>"
    }

    def __init__(self):
        self.bg_task = None

    async def make_rotating_apng(self, image_bytes: bytes) -> bytes:
        size = 512
        duration = 6
        fps = 30
        radius = size // 2

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input.jpg")
            out_path = os.path.join(tmpdir, "output.webp")

            with open(in_path, "wb") as f:
                f.write(image_bytes)

            filters = (
                f"crop='min(iw,ih):min(iw,ih)',"
                f"scale={size}:{size}:flags=lanczos,"
                f"format=rgba,"
                f"geq=r='r(X,Y)':a='if(gt(hypot(X-{radius},Y-{radius}),{radius}),0,alpha(X,Y))',"
                f"rotate='2*PI*t/{duration}:bilinear=1:c=0x00000000:ow={size}:oh={size}'"
            )

            cmd =[
                'ffmpeg', '-y',
                '-loop', '1', '-i', in_path,
                '-vf', filters,
                '-t', str(duration),
                '-r', str(fps),
                '-vcodec', 'libwebp',
                '-lossless', '0',
                '-compression_level', '6',
                '-q:v', '70',
                '-loop', '0',
                '-preset', 'default',
                '-an',
                out_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            _, stderr = await process.communicate()

            if process.returncode != 0:
                print(f"[FFmpeg Error]: {stderr.decode()}")
                return b""

            try:
                with open(out_path, "rb") as f:
                    result_bytes = f.read()
                return result_bytes
            except FileNotFoundError:
                print("Ошибка: FFmpeg не создал выходной файл.")
                return b""

    async def get_current_song(self) -> dict:
        
        username = await self._get("username")
        api_key = await self._get("api_key")
        
        if not username or not api_key:
            return None

        url = f"http://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={username}&api_key={api_key}&format=json&limit=1"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tracks = data.get("recenttracks", {}).get("track",[])
                        
                        if tracks:
                            track = tracks[0]
                            is_playing = "@attr" in track and track["@attr"].get("nowplaying") == "true"
                            
                            if is_playing:
                                artist = track.get("artist", {}).get("#text", "Unknown Artist")
                                name = track.get("name", "Unknown Track")
                                album = track.get("album", {}).get("#text") or "Unknown Album"

                                images = track.get("image",[])
                                cover_url = images[-1].get("#text") if images else None
                                tracks = data.get("recenttracks", {}).get("track", [])

                                if tracks:
                                    current_track = tracks[0]
                                    
                                    song_url = current_track.get("url", "")
                                    
                                    images = current_track.get("image", [])
                                    cover_url = images[-1].get("#text") if images else None
                                else:
                                    song_url = ""
                                    cover_url = None

                                animated_cover = None

                                if cover_url:
                                    async with session.get(cover_url, timeout=10) as img_resp:
                                        if img_resp.status == 200:
                                            image_bytes = await img_resp.read()
                                            animated_cover = await self.make_rotating_apng(image_bytes)

                                return {
                                    "text": f"{artist} — {name}",
                                    "image": animated_cover,
                                    "image_url": cover_url,
                                    "artist": artist,
                                    "track": name,
                                    "album": album,
                                    "song_url": song_url
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
            return await mx.answer(self.strings.get("no_args"))

        username = args.strip()
        
        await self._set("username", username)
        
        await mx.answer(
            self.strings.get("config_saved").format(
                utils.escape_html(username)
            )
        )

    @loader.command()
    async def np(self, mx, event: MessageEvent):
        """Узнать текущий играющий трек"""
        
        if not await self._get("username"):
            return await mx.answer(self.strings.get("no_username"))

        song = await self.get_current_song()
        if song:
            text = self.strings.get("now_playing").format(utils.escape_html(song["text"]))
        else:
            text = self.strings.get("not_playing")
            
        await mx.answer(text)

    @loader.command()
    async def lfauto(self, mx, event: MessageEvent):
        """Запустить автообновление играющего трека (RPC)"""
        
        if not await self._get("username"):
            return await mx.answer(self.strings.get("no_username"))

        if self.bg_task and not self.bg_task.done():
            self.bg_task.cancel()

        evt_id = await mx.answer(self.strings.get("auto_started"))
        
        await self._set("room_id", event.room_id)
        await self._set("event_id", evt_id)

        self.bg_task = asyncio.create_task(self._auto_update_loop(mx))

    @loader.command()
    async def lfstop(self, mx, event: MessageEvent):
        """Остановить автообновление"""
        if self.bg_task and not self.bg_task.done():
            self.bg_task.cancel()
            self.bg_task = None
            
        await self._set("room_id", None)
        await self._set("event_id", None)
        
        await mx.answer(self.strings.get("auto_stopped"))

    async def upload_cover(self, mx, file_bytes: bytes) -> str | None:
        try:
            mxc = await mx.client.upload_media(
                file_bytes,
                mime_type="image/webp",
                filename="cover.webp"
            )
            return str(mxc)
        except Exception as e:
            print(f"[upload_cover] error: {e}")
            return None
    
    async def _auto_update_loop(self, mx):
        last_song = None

        while True:
            try:
                current_song = await self.get_current_song()

                cover_mxc = None

                if current_song and current_song.get("image"):
                    cover_mxc = await self.upload_cover(mx, current_song["image"])

                if current_song != last_song:
                    last_song = current_song

                    if current_song:
                        await mx.client.set_rpc_media(
                            artist=current_song["artist"],
                            album=current_song["album"],
                            track=current_song["track"],
                            cover_art=cover_mxc or "mxc://pashahatsune.pp.ua/Pog8OuodZbmX73kEHCO1V77VDh6ctM8e",
                            player="Last.fm",
                            streaming_link=current_song["song_url"]
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

    async def _matrix_start(self, mx):
        if not await self._get("api_key"):
            await self._set("api_key", "460cda35be2fbf4f28e8ea7a38580730")
            
        if not await self._get("username"):
            await self._set("username", "MikuSv0")

        if await self._get("room_id") and await self._get("event_id"):
            self.bg_task = asyncio.create_task(self._auto_update_loop(mx))