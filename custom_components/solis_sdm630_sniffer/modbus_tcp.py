"""Small read-only Modbus TCP transport; no write function is implemented."""

import asyncio
import struct
from time import monotonic


class ModbusError(Exception):
    """A malformed or rejected Modbus response."""


class UnsupportedRegisters(ModbusError):
    """The server explicitly rejected a register range."""


class ModbusReader:
    """One serialized connection with bounded reads and inter-request spacing."""

    def __init__(self, host: str, port: int, unit: int, *, timeout: float = 5):
        self.host, self.port, self.unit = host, port, unit
        self.timeout = timeout
        self._writer = None
        self._reader = None
        self._transaction = 0
        self._last_response = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )
        return self

    async def __aexit__(self, *_):
        if self._writer:
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), self.timeout)
            except (OSError, TimeoutError):
                pass

    async def read(self, address: int, count: int) -> tuple[int, ...]:
        """Read input registers (04), never holding registers or coils."""
        if not 1 <= count <= 50 or not 0 <= address <= 65536 - count:
            raise ValueError("Invalid input register range")
        async with self._lock:
            await asyncio.sleep(max(0, self._last_response + 0.350 - monotonic()))
            try:
                async with asyncio.timeout(self.timeout):
                    self._transaction = (self._transaction + 1) % 65536
                    self._writer.write(
                        struct.pack(
                            ">HHHBBHH",
                            self._transaction,
                            0,
                            6,
                            self.unit,
                            4,
                            address,
                            count,
                        )
                    )
                    await self._writer.drain()
                    header = await self._reader.readexactly(7)
                    transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                    if (transaction, protocol, unit) != (
                        self._transaction,
                        0,
                        self.unit,
                    ) or not 3 <= length <= 103:
                        raise ModbusError("Invalid response header")
                    body = await self._reader.readexactly(length - 1)
                    if body[0] == 0x84 and len(body) == 2:
                        if body[1] == 2:
                            raise UnsupportedRegisters("Illegal input register address")
                        raise ModbusError(f"Modbus exception {body[1]}")
                    if len(body) != 2 + count * 2 or body[:2] != bytes((4, count * 2)):
                        raise ModbusError("Invalid response function or byte count")
                    return struct.unpack(">" + "H" * count, body[2:])
            except asyncio.IncompleteReadError as err:
                raise ModbusError("Truncated response") from err
            finally:
                self._last_response = monotonic()
