import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import sys
import time
import uuid
from abc import ABC
from typing import Any, AsyncGenerator, Dict, Optional, Callable

import aiohttp
from loguru import logger
from mautrix.client import Client
from mautrix.client.state_store import MemoryStateStore as BaseMemoryStateStore
from mautrix.crypto.attachments import encrypt_attachment
from mautrix.crypto.store import MemoryCryptoStore as BaseMemoryCryptoStore
from mautrix.types import (
    CrossSigningUsage,
    EventType,
    TOFUSigningKey,
    ToDeviceEvent,
    TrustState,
)
from mautrix.util.config import BaseFileConfig, ConfigUpdateHelper, RecursiveDict
from olm.sas import Sas
from ruamel.yaml.comments import CommentedMap

from . import utils


EMOJI_LIST =[
    "Dog", "Cat", "Lion", "Horse", "Unicorn", "Pig", "Elephant", 
    "Rabbit", "Panda", "Rooster", "Penguin", "Turtle", "Fish", 
    "Octopus", "Butterfly", "Flower", "Tree", "Cactus", "Mushroom", 
    "Globe", "Moon", "Cloud", "Fire", "Banana", "Apple", "Strawberry", 
    "Corn", "Pizza", "Cake", "Heart", "Smiley", "Robot", "Hat", 
    "Glasses", "Spanner", "Santa", "Thumbs Up", "Umbrella", "Hourglass", 
    "Clock", "Gift", "Light Bulb", "Book", "Pencil", "Paperclip", 
    "Scissors", "Lock", "Key", "Hammer", "Telephone", "Flag", 
    "Train", "Bicycle", "Aeroplane", "Rocket", "Trophy", "Ball", 
    "Guitar", "Trumpet", "Bell", "Anchor", "Headphones", "Folder", "Pin"
]


import asyncio

class ModuleConfig:
    def __init__(self, getter_func, setter_func, schema: dict):
        self._getter = getter_func
        self._setter = setter_func
        # schema  {"limit": ConfigValue(10, "...")}
        self._schema = schema
        self._cache = {key: cfg.default for key, cfg in schema.items()}

    async def _load_from_db(self):
        """Вызывается при инициализации модуля."""
        for key, cfg in self._schema.items():
            db_val = await self._getter(key, cfg.default)
            self._cache[key] = cfg._convert(db_val)

    def __getitem__(self, key):
        return self._cache.get(key)

    def set(self, key: str, raw_value: Any) -> bool:
        """
        Устанавливает значение, валидирует его и пишет в БД.
        Возвращает True если успешно.
        """
        if key not in self._schema:
            return False
        
        cfg = self._schema[key]
        try:
            converted = cfg._convert(raw_value)
            if cfg.validator and not cfg.validator(converted):
                return False
            
            self._cache[key] = converted
            asyncio.create_task(self._setter(key, converted))
            return True
        except Exception:
            return False

    def get_description(self, key):
        return self._schema[key].description if key in self._schema else ""


class ConfigValue:
    def __init__(
        self,
        default: Any,
        description: str = "",
        validator: Optional[Callable[[Any], bool]] = None
    ):
        self.default = default
        self.description = description
        self.validator = validator
        self.type = type(default)

    def _convert(self, val: Any) -> Any:
        """Приводит входное значение (обычно строку из чата) к нужному типу."""
        if isinstance(val, self.type):
            return val
        
        if isinstance(val, str):
            if self.type == bool:
                return val.lower() in ("true", "yes", "1", "y", "on")
            if self.type == int:
                return int(val)
            if self.type == float:
                return float(val)
            if self.type == list or self.type == dict:
                return json.loads(val)
        return val


class Module(ABC):
    __origin__ = "<unknown>"
    __module_hash__ = "unknown"
    __source__ = ""

    config = {}
    strings = {}

    async def _internal_init(self, name, db, loader_or_dict, is_core: bool):
        self.name = name
        self._is_core = is_core
        self.enabled = True
        self.logger = logger.bind(name=self.name)
        
        if is_core:
            self._db = db
            self.loader = loader_or_dict 
            self.allmodules = loader_or_dict.active_modules 
        else:
            self._db = None
            self.loader = None
            self.allmodules = loader_or_dict

        self._get = db.get
        self._set = db.set

        self.strings = getattr(self.__class__, "strings", {}).copy()
        self.friendly_name = self.strings.get("name") or self.config.get("name") or self.__class__.__name__

        schema = getattr(self.__class__, "config", {})
        self.config = ModuleConfig(
            self._get,
            self._set,
            schema
        )
        await self.config._load_from_db()

        self._commands = {}
        for cmd_name, func in utils.get_commands(self.__class__).items():
            self._commands[cmd_name] = getattr(self, func.__name__)

    def _help(self):
        return self.strings.get("_cls_doc", "No description available")

    @property
    def commands(self):
        return self._commands

    async def _get(self, key, default=None): 
        return await self._db.get(self.name, key, default)
        
    async def _set(self, key, value): 
        return await self._db.set(self.name, key, value)

    async def _matrix_start(self, mx):
        pass

    async def _matrix_message(self, mx, event):
        pass

    async def _matrix_member(self, mx, event):
        pass

    def _matrix_stop(self, mx):
        pass

    async def _matrix_poll(self, mx, pollcount):
        pass


class Config(BaseFileConfig):
    def __init__(self, path: str, base_path: str, db: Any = None) -> None:
        super().__init__(path, base_path)
        self.db = db
        self.owner = "core"
        
        self._default_values = {
            "matrix": {
                "base_url": "",
                "username": "",
                "password": "",
                "device_id": "",
                "access_token": "",
                "log_room_id": "",
                "owner": ""
            },
            "logging": {"version": 1}
        }

        self._data = RecursiveDict(self._default_values, CommentedMap)

    def load_base(self) -> RecursiveDict:
        return RecursiveDict(self._default_values, CommentedMap)

    def load(self) -> None:
        pass

    def save(self) -> None:
        pass

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("matrix")
        helper.copy("logging")

    async def load_from_db(self) -> None:
        if not self.db: 
            return

        async def fetch_recursive(data_dict: dict, prefix=""):
            for key, value in data_dict.items():
                full_key = f"{prefix}{key}"
                if isinstance(value, dict):
                    await fetch_recursive(value, f"{full_key}.")
                else:
                    db_value = await self.db.get(self.owner, full_key)
                    if db_value is not None:
                        self[full_key] = db_value

        await fetch_recursive(self._default_values)

    async def update_db_key(self, key: str, value: Any) -> None:
        self[key] = value
        if self.db:
            await self.db.set(self.owner, key, value)


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
            
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
            
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class MemoryCryptoStore(BaseMemoryCryptoStore):
    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None, None]:
        yield

    async def put_cross_signing_key(self, user_id: str, usage: CrossSigningUsage, key: str) -> None:
        try:
            current = self._cross_signing_keys[user_id][usage]
            self._cross_signing_keys[user_id][usage] = TOFUSigningKey(key=key, first=current.first)
        except KeyError:
            self._cross_signing_keys.setdefault(user_id, {})[usage] = TOFUSigningKey(key=key, first=key)


class CustomMemoryStateStore(BaseMemoryStateStore):
    async def find_shared_rooms(self, user_id: str) -> list[str]:
        shared =[]
        for room_id, members in getattr(self, "members", {}).items():
            if user_id in members:
                shared.append(room_id)
        return shared


class BotSASVerification:
    def __init__(self, client: Client):
        self.client = client
        self.sessions: Dict[str, Dict[str, Any]] = {}
        logger.info("BotSASVerification initialized")
        self.verified_event = asyncio.Event()

    def get_canonical_json(self, data: dict) -> str:
        clean_data = {k: v for k, v in data.items() if not k.startswith("__mautrix")}
        return json.dumps(clean_data, separators=(',', ':'), sort_keys=True, ensure_ascii=False)

    async def handle_decrypted_event(self, evt: ToDeviceEvent):
        t = evt.type.t if hasattr(evt.type, "t") else str(evt.type)
        if "m.key.verification." not in t:
            return
        
        if t == "m.key.verification.request":
            await self.handle_request(evt)
        elif t == "m.key.verification.ready":
            await self.handle_ready(evt)
        elif t == "m.key.verification.start":
            await self.handle_start(evt)
        elif t == "m.key.verification.accept":
            await self.handle_accept(evt)
        elif t == "m.key.verification.key":
            await self.handle_key(evt)
        elif t == "m.key.verification.mac":
            await self.handle_mac(evt)
        elif t == "m.key.verification.cancel":
            self.sessions.pop(evt.content.get("transaction_id"), None)

    async def start_verification(self, user_id: str, device_id: str, room_id: str):
        txn_id = f"v-{uuid.uuid4().hex[:8]}"
        self.sessions[txn_id] = {
            "sas": Sas(), "user_id": user_id, "device_id": device_id,
            "role": "alice", "room_id": room_id,
            "bot_mac_sent": False, "other_mac_received": False
        }
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.request", EventType.Class.TO_DEVICE),
            user_id, device_id, 
            {
                "from_device": self.client.device_id,
                "methods": ["m.sas.v1"],
                "transaction_id": txn_id,
                "timestamp": int(time.time() * 1000)
            }
        )
        return txn_id

    async def handle_ready(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        s = self.sessions.get(txn_id)
        if not s or s["role"] != "alice":
            return
        start_content = {
            "from_device": self.client.device_id, "method": "m.sas.v1",
            "key_agreement_protocols":["curve25519-hkdf-sha256", "curve25519"],
            "hashes": ["sha256"], "message_authentication_codes":["hkdf-hmac-sha256"],
            "short_authentication_string": ["emoji"], "transaction_id": txn_id
        }
        s["start_content"] = start_content
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.start", EventType.Class.TO_DEVICE),
            s["user_id"], s["device_id"], start_content
        )

    async def handle_accept(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        s = self.sessions.get(txn_id)
        if not s or s["role"] != "alice":
            return
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.key", EventType.Class.TO_DEVICE),
            s["user_id"], s["device_id"], {"transaction_id": txn_id, "key": s["sas"].pubkey.replace("=", "")}
        )

    async def handle_request(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        self.sessions[txn_id] = {
            "sas": Sas(), "user_id": evt.sender, "device_id": evt.content.get("from_device") or evt.sender_device,
            "role": "bob", "room_id": None, "bot_mac_sent": False, "other_mac_received": False
        }
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.ready", EventType.Class.TO_DEVICE),
            evt.sender, self.sessions[txn_id]["device_id"], {"transaction_id": txn_id, "methods":["m.sas.v1"]}
        )

    async def handle_start(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        s = self.sessions.get(txn_id)
        if not s or s["role"] != "bob":
            return
        sas = s["sas"]
        start_content = evt.content.serialize() if hasattr(evt.content, "serialize") else evt.content
        s["start_content"] = start_content
        commitment_str = sas.pubkey.replace("=", "") + self.get_canonical_json(start_content)
        commitment = base64.b64encode(hashlib.sha256(commitment_str.encode("utf-8")).digest()).decode().replace("=", "")
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.accept", EventType.Class.TO_DEVICE),
            s["user_id"], s["device_id"], {
                "transaction_id": txn_id, "method": "m.sas.v1", "key_agreement_protocol": "curve25519-hkdf-sha256",
                "hash": "sha256", "message_authentication_code": "hkdf-hmac-sha256", 
                "short_authentication_string": ["emoji"], "commitment": commitment
            }
        )

    async def handle_key(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        s = self.sessions.get(txn_id)
        if not s:
            return
        their_key = evt.content.get("key")
        s["sas"].set_their_pubkey(their_key + "=" * ((4 - len(their_key) % 4) % 4))
        my_pubkey = s["sas"].pubkey.replace("=", "")
        
        if s["role"] == "bob":
            await self.client.send_to_one_device(
                EventType.find("m.key.verification.key", EventType.Class.TO_DEVICE),
                s["user_id"], s["device_id"], {"transaction_id": txn_id, "key": my_pubkey}
            )

        a_id, a_dev, a_pk = (self.client.mxid, self.client.device_id, my_pubkey) if s["role"] == "alice" else (s['user_id'], s['device_id'], their_key)
        b_id, b_dev, b_pk = (s['user_id'], s['device_id'], their_key) if s["role"] == "alice" else (self.client.mxid, self.client.device_id, my_pubkey)
        sas_info = f"MATRIX_KEY_VERIFICATION_SAS|{a_id}|{a_dev}|{a_pk}|{b_id}|{b_dev}|{b_pk}|{txn_id}"
        sas_bytes = s["sas"].generate_bytes(sas_info.encode("utf-8"), 6)
        val = int.from_bytes(sas_bytes, "big")
        emojis =[f"{ (val >> (42 - (i * 6))) & 0x3F }:{EMOJI_LIST[(val >> (42 - (i * 6))) & 0x3F]}" for i in range(7)]
        
        if s.get("room_id"):
            await self.client.send_notice(s["room_id"], f"📊 <b>VERIFY EMOJI:</b>\n\n<code>{' | '.join(emojis)}</code>\n\n⏳ Confirming automatically...")

        await asyncio.sleep(3)
        asyncio.create_task(self._send_actual_mac(txn_id))

    async def _send_actual_mac(self, txn_id: str):
        s = self.sessions.get(txn_id)
        if not s or s["bot_mac_sent"]:
            return
        
        sas = s["sas"]
        user_id, device_id = self.client.mxid, self.client.device_id
        other_user_id, other_device_id = s['user_id'], s['device_id']
        my_pub_key = self.client.crypto.account.identity_keys['ed25519'].rstrip("=")
        key_id = f"ed25519:{device_id}"

        mac_dict = {key_id: sas.calculate_mac(my_pub_key, "MATRIX_KEY_VERIFICATION_MAC" + user_id + device_id + other_user_id + other_device_id + txn_id + key_id).rstrip("=")}
        keys_mac = sas.calculate_mac(key_id, "MATRIX_KEY_VERIFICATION_MAC" + user_id + device_id + other_user_id + other_device_id + txn_id + "KEY_IDS").rstrip("=")
        
        await self.client.send_to_one_device(
            EventType.find("m.key.verification.mac", EventType.Class.TO_DEVICE),
            other_user_id, other_device_id, {"transaction_id": txn_id, "mac": mac_dict, "keys": keys_mac}
        )
        s["bot_mac_sent"] = True
        await self._maybe_finish(txn_id)

    async def handle_mac(self, evt: ToDeviceEvent):
        txn_id = evt.content.get("transaction_id")
        s = self.sessions.get(txn_id)
        if not s:
            return
        s["other_mac_received"] = True
        logger.info(f"Received MAC from device {s['device_id']}")
        await self._maybe_finish(txn_id)

    async def _maybe_finish(self, txn_id: str):
        s = self.sessions.get(txn_id)
        if s and s["bot_mac_sent"] and s["other_mac_received"]:
            await self.client.send_to_one_device(
                EventType.find("m.key.verification.done", EventType.Class.TO_DEVICE),
                s["user_id"], s["device_id"], {"transaction_id": txn_id}
            )
            
            device = await self.client.crypto.crypto_store.get_device(s["user_id"], s["device_id"])
            if device:
                device.trust = TrustState.VERIFIED
                await self.client.crypto.crypto_store.put_devices(s["user_id"], {s["device_id"]: device})
                
                logger.success(f"🎊 SUCCESS: Device {s['device_id']} verified locally!")
                if s.get("room_id"):
                    await self.client.send_notice(s["room_id"], f"✅ Device {s['device_id']} verified!")
            
            self.sessions.pop(txn_id, None)