import asyncio
from dataclasses import dataclass, field
from typing import Callable

PREFIX = bytes([0x56, 0x54, 0x55])
DIR_OUTGOING = 0x30
DIR_INCOMING = 0x31

CMD_ACK = 0x00
CMD_LOGIN = 0x01
CMD_HEARTBEAT = 0x07
CMD_ROOM_METADATA = 0x1A
CMD_ROOM_COUNT = 0x1D
CMD_TOGGLE_NODE_STATUS = 0x1E
CMD_NODE_METADATA = 0x1F
CMD_NODE_COUNT = 0x24
CMD_TOGGLE_KEY_STATUS = 0x28
CMD_KEY_STATUS = 0x29
CMD_KEY_PARAMETERS = 0x2B
CMD_INTERNAL_UNIT_STATUSES = 0x60

KEY_ON = 0x4F
KEY_OFF = 0x46
KEY_RELEASED = 0x52

KEY_TYPE_NOT_EXIST = 0
KEY_TYPE_NOT_ACTIVE = 1
KEY_TYPE_TOGGLE = 2
KEY_TYPE_BLIND = 3
KEY_TYPE_PUSH_BUTTON = 4
KEY_TYPE_DIMMER = 5
KEY_TYPE_DIMMER_MW = 10
KEY_TYPE_BLIND_MW = 11

HEARTBEAT_INTERVAL = 2.5


@dataclass
class NodeMetaData:
    id: int = 0
    room_id: int = 0
    mac_address: str = ""
    total_keys: int = 0
    keys_list: list[dict] = field(default_factory=list)


@dataclass
class RoomMetaData:
    id: int = 0
    name: str = ""


@dataclass
class KeyStatusResponse:
    node_id: int = 0
    key_id: int = 0
    power: int = 0
    is_on: bool = False


class VitreaClient:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._msg_id = 0
        self._buffer = bytearray()
        self._pending: dict[int, asyncio.Future] = {}
        self._cmd_pending: dict[int, asyncio.Future] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        self._key_status_callbacks: list[Callable] = []

    def _next_msg_id(self) -> int:
        mid = self._msg_id
        self._msg_id = (self._msg_id + 1) & 0xFF
        return mid

    def _build_message(self, command_id: int, data: bytes = b"") -> tuple[int, bytes]:
        msg_id = self._next_msg_id()
        data_length = len(data) + 2
        buf = bytearray(PREFIX)
        buf.append(DIR_OUTGOING)
        buf.append(command_id)
        buf.append((data_length >> 8) & 0xFF)
        buf.append(data_length & 0xFF)
        buf.append(msg_id)
        buf.extend(data)
        checksum = sum(buf) & 0xFF
        buf.append(checksum)
        return msg_id, bytes(buf)

    async def _send_command(self, command_id: int, data: bytes = b"", wait_cmd: bool = False) -> bytes | None:
        msg_id, raw = self._build_message(command_id, data)
        fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        if wait_cmd:
            self._cmd_pending[command_id] = fut
        else:
            self._pending[msg_id] = fut
        self._writer.write(raw)
        await self._writer.drain()
        return await asyncio.wait_for(fut, timeout=5.0)

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        self._reader_task = asyncio.ensure_future(self._reader_loop())
        await self._send_command(CMD_HEARTBEAT)
        await self.login()
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    async def disconnect(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._writer:
            self._writer.close()
            self._writer = None
        self._reader = None
        self._buffer.clear()

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                _, raw = self._build_message(CMD_HEARTBEAT)
                self._writer.write(raw)
                await self._writer.drain()
            except Exception:
                break

    async def _reader_loop(self) -> None:
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    break
                self._buffer.extend(chunk)
                self._process_buffer()
        except asyncio.CancelledError:
            pass

    def _process_buffer(self) -> None:
        while True:
            idx = self._buffer.find(PREFIX)
            if idx == -1:
                self._buffer.clear()
                return
            if idx > 0:
                del self._buffer[:idx]
            if len(self._buffer) < 8:
                return
            data_length = (self._buffer[5] << 8) | self._buffer[6]
            total = data_length + 7
            if len(self._buffer) < total:
                return
            msg = bytes(self._buffer[:total])
            del self._buffer[:total]
            self._dispatch(msg)

    def _dispatch(self, msg: bytes) -> None:
        cmd = msg[4]
        msg_id = msg[7]
        if cmd == CMD_ACK:
            fut = self._pending.pop(msg_id, None)
            if fut and not fut.done():
                fut.set_result(msg)
            return
        if cmd == CMD_KEY_STATUS:
            self._handle_key_status_push(msg)
        fut = self._cmd_pending.pop(cmd, None)
        if fut and not fut.done():
            fut.set_result(msg)
        fut2 = self._pending.pop(msg_id, None)
        if fut2 and not fut2.done():
            fut2.set_result(msg)

    def _handle_key_status_push(self, msg: bytes) -> None:
        if len(msg) < 11:
            return
        status = KeyStatusResponse(
            node_id=msg[8],
            key_id=msg[9],
            power=msg[10],
            is_on=msg[10] == KEY_ON,
        )
        for cb in self._key_status_callbacks:
            cb(status)

    async def login(self) -> None:
        u = self._username.encode("utf-16-le")
        p = self._password.encode("utf-16-le")
        data = bytes([len(u)]) + u + bytes([len(p)]) + p
        await self._send_command(CMD_LOGIN, data)

    async def get_node_count(self) -> int:
        resp = await self._send_command(CMD_NODE_COUNT, wait_cmd=True)
        return resp[8]

    async def get_room_count(self) -> int:
        resp = await self._send_command(CMD_ROOM_COUNT, wait_cmd=True)
        return resp[8]

    async def get_node_metadata(self, node_id: int) -> NodeMetaData:
        resp = await self._send_command(CMD_NODE_METADATA, bytes([node_id]), wait_cmd=True)
        nid = resp[8]
        mac = ":".join(f"{b:02X}" for b in resp[9:17])
        total_keys = resp[18]
        keys = []
        for i in range(total_keys):
            keys.append({"id": i, "type": resp[19 + i]})
        offset_start = 19 + total_keys
        room_id = resp[offset_start + 7] if offset_start + 7 < len(resp) - 1 else 0
        return NodeMetaData(id=nid, room_id=room_id, mac_address=mac, total_keys=total_keys, keys_list=keys)

    async def get_room_metadata(self, room_id: int) -> RoomMetaData:
        resp = await self._send_command(CMD_ROOM_METADATA, bytes([room_id]), wait_cmd=True)
        rid = resp[8]
        name_bytes = resp[11:-1]
        name = name_bytes.decode("utf-16-le", errors="replace").rstrip("\x00")
        return RoomMetaData(id=rid, name=name)

    async def get_key_status(self, node_id: int, key_id: int) -> KeyStatusResponse:
        resp = await self._send_command(CMD_KEY_STATUS, bytes([node_id, key_id]), wait_cmd=True)
        return KeyStatusResponse(
            node_id=resp[8],
            key_id=resp[9],
            power=resp[10],
            is_on=resp[10] == KEY_ON,
        )

    async def toggle_key(self, node_id: int, key_id: int, power: int, dimmer: int = 0) -> None:
        timer_high = 0
        timer_low = 0
        data = bytes([node_id, key_id, power, dimmer, timer_high, timer_low])
        await self._send_command(CMD_TOGGLE_KEY_STATUS, data)

    def on_key_status(self, callback: Callable) -> None:
        self._key_status_callbacks.append(callback)

    async def discover_devices(self) -> list[dict]:
        count = await self.get_node_count()
        devices = []
        for i in range(1, count + 1):
            node = await self.get_node_metadata(i)
            devices.append({
                "node_id": node.id,
                "room_id": node.room_id,
                "mac_address": node.mac_address,
                "total_keys": node.total_keys,
                "keys": node.keys_list,
            })
        return devices
