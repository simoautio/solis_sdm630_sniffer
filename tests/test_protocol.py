"""Protocol tests run without importing Home Assistant."""

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

# Load the standalone parser without executing the integration's HA entrypoint.
spec = importlib.util.spec_from_file_location(
    "sniffer_protocol",
    Path(__file__).parents[1] / "custom_components/solis_sdm630_sniffer/protocol.py",
)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)
StreamParser = protocol.StreamParser
crc16 = protocol.crc16


def frame(body):
    return body + crc16(body).to_bytes(2, "little")


def request(start=0, count=2, slave=1):
    return frame(struct.pack(">BBHH", slave, 4, start, count))


def response(*values, slave=1):
    data = struct.pack(">" + "f" * len(values), *values)
    return frame(bytes([slave, 4, len(data)]) + data)


def values(updates):
    return [update.values for update in updates]


def test_known_crc():
    assert crc16(bytes.fromhex("010400000002")) == 0xCB71
    assert request() == bytes.fromhex("01040000000271cb")


@pytest.mark.parametrize("cut", range(1, 17))
def test_all_fragment_boundaries(cut):
    data = request() + response(230.5)
    parser = StreamParser()
    updates = parser.feed(data[:cut], now=0)
    updates += parser.feed(data[cut:], now=0.1)
    assert values(updates) == [{0: 230.5}]
    assert parser.buffer_size == 0


def test_one_byte_chunks():
    parser = StreamParser()
    updates = []
    for byte in request() + response(230.5):
        updates += parser.feed(bytes([byte]), now=0)
    assert values(updates) == [{0: 230.5}]


def test_concatenated_frames_and_nonzero_offsets():
    parser = StreamParser()
    data = request() + response(230.5) + request(52, 2) + response(-1200.25)
    assert values(parser.feed(data, now=0)) == [{0: 230.5}, {52: -1200.25}]


def test_pairing_replacement_and_unsolicited_response():
    parser = StreamParser()
    assert parser.feed(response(230.5), now=0) == []
    assert values(parser.feed(request() + request(6) + response(4.5), now=1)) == [
        {6: 4.5}
    ]
    assert parser.feed(response(5), now=1) == []


def test_mismatch_consumes_pending_request():
    parser = StreamParser()
    assert parser.feed(request(0, 4) + response(230.5), now=0) == []
    assert parser.feed(response(230.5, 231), now=1) == []


def test_bad_crc_recovery(caplog):
    parser = StreamParser()
    bad = bytearray(response(230.5))
    bad[-1] ^= 0xFF
    with caplog.at_level("DEBUG"):
        updates = parser.feed(request() + bad + request(6) + response(4.5), now=0)
    assert values(updates) == [{6: 4.5}]
    assert parser.counters["crc_failures"] >= 1
    assert "CRC" in caplog.text
    assert "request" in caplog.text


def test_noise_clears_pairing_and_recovers():
    parser = StreamParser()
    assert parser.feed(request() + b"noise" + response(230.5), now=0) == []
    assert values(parser.feed(request() + response(231), now=1)) == [{0: 231}]


def test_exception_and_expiration():
    parser = StreamParser()
    assert parser.feed(request() + frame(bytes([1, 0x84, 2])), now=0) == []
    assert parser.feed(response(230.5), now=1) == []
    parser.feed(request(), now=2)
    assert parser.feed(response(230.5), now=8) == []


def test_other_slave():
    parser = StreamParser()
    assert parser.feed(request(slave=2) + response(230.5, slave=2), now=0) == []
    assert values(parser.feed(request() + response(230.5), now=1)) == [{0: 230.5}]


def test_float_pairs_and_nonfinite():
    parser = StreamParser()
    assert values(parser.feed(request(6, 6) + response(1.5, -2.25, 3.125), now=0)) == [
        {6: 1.5, 8: -2.25, 10: 3.125}
    ]
    assert values(
        parser.feed(request(0, 4) + response(float("nan"), float("inf")), now=1)
    ) == [{}]


def test_odd_start_never_misaligns_float():
    parser = StreamParser()
    # Low word of voltage 1, complete voltage 2, then half of voltage 3.
    data = b"\x00\x00" + struct.pack(">f", 231.5) + b"\x00\x00"
    assert values(
        parser.feed(request(1, 4) + frame(b"\x01\x04\x08" + data), now=0)
    ) == [{2: 231.5}]


def test_bounded_buffer_and_large_valid_payload():
    parser = StreamParser()
    assert parser.feed(b"\xff" * 10000, now=0) == []
    assert parser.buffer_size <= 4096
    assert len(parser.feed((request() + response(230.5)) * 1000, now=1)) == 1000


def test_reset_discards_fragment_and_pairing():
    parser = StreamParser()
    parser.feed(request() + response(230.5)[:4], now=0)
    parser.reset()
    assert parser.buffer_size == 0
    assert parser.pending is None
    assert parser.feed(response(230.5), now=1) == []


def test_fragmented_request_does_not_log_crc_failure():
    parser = StreamParser()
    for byte in request(342):
        parser.feed(bytes([byte]), now=0)
    assert parser.counters["crc_failures"] == 0
    assert values(parser.feed(response(1234), now=1)) == [{342: 1234}]


def test_fragment_with_crc_valid_request_inside_response_data():
    parser = StreamParser()
    embedded = request(6, 2)
    payload = embedded + struct.pack(">f", 232)
    reply = frame(b"\x01\x04\x0c" + payload)
    parser.feed(request(0, 6), now=0)
    assert parser.feed(reply[:11], now=0.1) == []
    updates = parser.feed(reply[11:], now=0.2)
    assert updates[0].values[4] == 232
    assert parser.counters["requests"] == 1


@pytest.mark.parametrize("cut", range(1, 9))
def test_response_prefix_is_also_crc_valid_request(cut):
    # This valid response's first eight bytes ALSO pass a request CRC.
    reply = bytes.fromhex("010404400001312e00")
    parser = StreamParser()
    parser.feed(request(), now=0)
    updates = parser.feed(reply[:cut], now=0.1)
    updates += parser.feed(reply[cut:], now=0.2)
    assert values(updates) == [{0: struct.unpack(">f", reply[3:7])[0]}]
    assert parser.counters["requests"] == 1


def test_captured_request_only_stream_and_recovery():
    # Exact CRC-valid request seen 1,710 times in the two-minute field capture.
    captured_request = bytes.fromhex("01040034000a31c3")
    parser = StreamParser()
    for index in range(1710):
        assert parser.feed(captured_request, now=index * 0.07) == []
    assert parser.counters["requests"] == 1710
    assert parser.counters["replaced_requests"] == 1709
    assert parser.counters["paired_responses"] == 0
    assert parser.counters["expired_requests"] == 0
    assert parser.buffer_size == 0
    assert parser.last_request.start == 52
    assert parser.last_request.count == 10
    assert parser.last_request.received_at == 1709 * 0.07

    # Synthetic reply: validates recovery, not a measurement from the capture.
    assert values(parser.feed(response(-1200, 0, 1300, 0, 500), now=120)) == [
        {52: -1200, 54: 0, 56: 1300, 58: 0, 60: 500}
    ]
    assert parser.pending is None
    assert parser.last_request.start == 52
    assert parser.counters["paired_responses"] == 1
    parser.reset()
    assert parser.last_request is None
    assert parser.counters["replaced_requests"] == 1709


def test_expired_or_answered_requests_are_not_counted_as_replaced():
    parser = StreamParser()
    parser.feed(request(), now=0)
    parser.feed(request(), now=6)
    assert parser.counters["expired_requests"] == 1
    assert parser.counters["replaced_requests"] == 0
    parser.feed(response(230), now=6.1)
    parser.feed(request(), now=6.2)
    assert parser.counters["replaced_requests"] == 0
