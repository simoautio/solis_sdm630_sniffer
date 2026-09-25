"""Passive Modbus RTU stream decoding; no I/O and no Home Assistant imports."""

from __future__ import annotations

import logging
import math
import struct
from collections import Counter
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = 5.0
MAX_BUFFER = 4096


def crc16(data: bytes | bytearray) -> int:
    """Return Modbus CRC16; RTU transmits the low byte first."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


@dataclass(frozen=True)
class Request:
    """The latest observed request, never a request to transmit."""

    start: int
    count: int
    received_at: float


@dataclass(frozen=True)
class MeterUpdate:
    """A CRC-valid, paired response, including any finite complete floats."""

    values: dict[int, float]


class StreamParser:
    """Recover RTU frames across arbitrary ordered MQTT payload boundaries.

    Modbus has no transaction ID. Prefer a matching response when both frame
    interpretations validate. CRC cannot disambiguate every possible stream.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.pending: Request | None = None
        self.last_request: Request | None = None
        self._last_byte_at: float | None = None
        self.counters: Counter[str] = Counter()

    @property
    def buffer_size(self) -> int:
        """Return retained bytes, not raw traffic."""
        return len(self._buffer)

    def reset(self) -> None:
        """Forget partial frames and pairing, retaining diagnostic counters."""
        self._buffer.clear()
        self.pending = None
        self.last_request = None
        self._last_byte_at = None

    def feed(self, payload: bytes, now: float) -> list[MeterUpdate]:
        """Consume bytes using a caller-supplied monotonic timestamp."""
        if self.pending and now - self.pending.received_at >= REQUEST_TIMEOUT:
            self.pending = None
            self.counters["expired_requests"] += 1
        if (
            self._last_byte_at is not None
            and now - self._last_byte_at >= REQUEST_TIMEOUT
        ):
            self._buffer.clear()
        if payload:
            self._last_byte_at = now
        updates: list[MeterUpdate] = []
        # Drain incrementally so a large MQTT message cannot grow retained state.
        for offset in range(0, len(payload), MAX_BUFFER // 2):
            self._buffer.extend(payload[offset : offset + MAX_BUFFER // 2])
            self._drain(now, updates)
        return updates

    def _candidates(self, offset: int) -> tuple[list[tuple[str, int]], bool]:
        """Return complete CRC-valid interpretations and whether more bytes help."""
        data = self._buffer
        size = len(data) - offset
        if not size or not 1 <= data[offset] <= 247:
            return [], False
        if size < 2:
            return [], True
        function = data[offset + 1]
        if function not in (4, 0x84):
            return [], False
        if size < 3:
            return [], True
        lengths: list[tuple[str, int]] = []
        if function == 0x84:
            lengths.append(("exception", 5))
        else:
            byte_count = data[offset + 2]
            if 2 <= byte_count <= 250 and byte_count % 2 == 0:
                lengths.append(("response", byte_count + 5))
            if size < 6:
                lengths.append(("request", 8))
            else:
                start, count = struct.unpack_from(">HH", data, offset + 2)
                if 1 <= count <= 125 and start + count <= 65536:
                    lengths.append(("request", 8))
        valid = []
        incomplete = False
        for kind, length in lengths:
            if size < length:
                incomplete = True
                continue
            end = offset + length
            if crc16(data[offset : end - 2]) == int.from_bytes(
                data[end - 2 : end], "little"
            ):
                valid.append((kind, length))
        return valid, incomplete

    def _discard(self, count: int, *, crc_failure: bool = False) -> None:
        """Losing framing also loses confidence in an outstanding request."""
        if crc_failure:
            self.counters["crc_failures"] += 1
            _LOGGER.debug("CRC failure while resynchronizing RTU stream")
        self.counters["discarded_bytes"] += count
        del self._buffer[:count]
        self.pending = None

    def _drain(self, now: float, updates: list[MeterUpdate]) -> None:
        while self._buffer:
            if (
                self.pending
                and len(self._buffer) >= 3
                and self._buffer[:3] == bytes([1, 4, self.pending.count * 2])
                and len(self._buffer) < self.pending.count * 2 + 5
            ):
                # Even a complete request CRC may occur inside an unfinished
                # response, including across its header and float data.
                return
            valid, incomplete = self._candidates(0)
            if not valid:
                if incomplete:
                    # A damaged length may claim an indefinitely incomplete frame.
                    # Resume only at a fully CRC-validated later candidate.
                    later = next(
                        (
                            i
                            for i in range(1, len(self._buffer))
                            if self._candidates(i)[0]
                        ),
                        None,
                    )
                    if later is None:
                        return
                    self._discard(later, crc_failure=True)
                    continue
                looks_like_frame = (
                    len(self._buffer) >= 5
                    and 1 <= self._buffer[0] <= 247
                    and self._buffer[1] in (4, 0x84)
                )
                self._discard(1, crc_failure=looks_like_frame)
                continue
            # A valid request wins unless a matching response also validates.
            kind, length = next(
                (candidate for candidate in valid if candidate[0] == "request"),
                valid[0],
            )
            if self.pending:
                kind, length = next(
                    (
                        candidate
                        for candidate in valid
                        if candidate == ("response", self.pending.count * 2 + 5)
                    ),
                    (kind, length),
                )
            frame = bytes(self._buffer[:length])
            del self._buffer[:length]
            if frame[0] != 1:
                self.pending = None
                self.counters["other_slave_frames"] += 1
                continue
            self.counters[kind + "s"] += 1
            if kind == "request":
                start, count = struct.unpack_from(">HH", frame, 2)
                if self.pending is not None:
                    self.counters["replaced_requests"] += 1
                self.pending = self.last_request = Request(start, count, now)
                _LOGGER.debug(
                    "Decoded request: slave=1 function=04 start=%d count=%d",
                    start,
                    count,
                )
            elif kind == "exception":
                self.pending = None
                _LOGGER.debug("Meter exception: function=04 code=%d", frame[2])
            else:
                pending, self.pending = self.pending, None
                if pending is None or frame[2] != pending.count * 2:
                    self.counters["unpaired_responses"] += 1
                    _LOGGER.debug(
                        "Ignored response: no matching request (bytes=%d)", frame[2]
                    )
                    continue
                decoded: dict[int, float] = {}
                # All SDM630MCT float values start at even zero-based addresses.
                for address in range(
                    pending.start + pending.start % 2,
                    pending.start + pending.count - 1,
                    2,
                ):
                    value = struct.unpack_from(
                        ">f", frame, 3 + (address - pending.start) * 2
                    )[0]
                    if math.isfinite(value):
                        decoded[address] = value
                    else:
                        self.counters["nonfinite_values"] += 1
                self.counters["paired_responses"] += 1
                _LOGGER.debug(
                    "Decoded response: start=%d values=%s", pending.start, decoded
                )
                updates.append(MeterUpdate(decoded))
