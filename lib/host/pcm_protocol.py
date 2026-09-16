"""Strict, standard-library decoder for M128 transport v1.

Raw PCM is preserved in arrival order. No reordering, interpolation, gap filling
or clock reconstruction is implicit in this module.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import struct

MAGIC = b'M128'
HEADER_BYTES = 32
CHANNELS = 128
SAMPLE_RATE = 48000
FRAMES_PER_PACKET = 3
PCM_FRAME_BYTES = 384
RECORD_BYTES = 392
PAYLOAD_BYTES = 1208
ENCODING = 's24le'
HEADER = struct.Struct('>4sBBBBIHHQII')
FRAME_ID = struct.Struct('>Q')
U64_MASK = (1 << 64) - 1
FLAG_NAMES = ('saturation', 'preprocessor_queue_overflow',
              'processing_schedule_error', 'packetizer_framing_error')


class ProtocolError(ValueError):
    """Datagram does not satisfy the published M128 v1 wire format."""


@dataclass(frozen=True, slots=True)
class Frame:
    frame_id: int
    pcm: bytes

    def samples(self) -> tuple[int, ...]:
        """Decode signed 24-bit samples on demand, outside the capture hot path."""
        return tuple(int.from_bytes(self.pcm[i:i + 3], 'little', signed=True)
                     for i in range(0, PCM_FRAME_BYTES, 3))


@dataclass(frozen=True, slots=True)
class Packet:
    sequence: int
    epoch: int
    flags: int
    frames: tuple[Frame, ...]

    @property
    def flag_names(self) -> list[str]:
        return [name for bit, name in enumerate(FLAG_NAMES) if self.flags & (1 << bit)]


def decode_payload(payload: bytes) -> Packet:
    """Validate and decode one UDP payload (no Ethernet/IP/UDP headers)."""
    if len(payload) != PAYLOAD_BYTES:
        raise ProtocolError(f'payload length {len(payload)}; expected {PAYLOAD_BYTES}')
    magic, version, header_size, encoding, channels, rate, count, record_size, seq, epoch, flags = HEADER.unpack_from(payload)
    checks = ((magic, MAGIC, 'magic'), (version, 1, 'version'),
              (header_size, HEADER_BYTES, 'header size'), (encoding, 1, 'encoding'),
              (channels, CHANNELS, 'channels'), (rate, SAMPLE_RATE, 'sample rate'),
              (count, FRAMES_PER_PACKET, 'record count'), (record_size, RECORD_BYTES, 'record size'))
    for actual, expected, name in checks:
        if actual != expected:
            raise ProtocolError(f'invalid {name}: {actual!r}; expected {expected!r}')
    if flags & ~0xF:
        raise ProtocolError(f'reserved v1 flag bits set: 0x{flags:08x}')
    frames = tuple(Frame(FRAME_ID.unpack_from(payload, p)[0], payload[p + 8:p + RECORD_BYTES])
                   for p in range(HEADER_BYTES, PAYLOAD_BYTES, RECORD_BYTES))
    return Packet(seq, epoch, flags, frames)


class SequenceTracker:
    """Exact gap/duplicate accounting using merged received-sequence intervals.

    Missing counts cover the first observed sequence through the highest observed
    forward sequence. Reordered arrivals close gaps. Anything preceding capture
    start is classified separately. 64-bit wrap is handled by modular distance;
    one capture must span fewer than 2**63 sequence positions.
    """
    def __init__(self) -> None:
        self.first: int | None = None
        self.highest = -1
        self.ranges: list[tuple[int, int]] = []
        self.unique = 0
        self.duplicates = 0
        self.out_of_order = 0
        self.before_capture = 0
        self.forward_gap_observations = 0

    def observe(self, value: int) -> tuple[str, int]:
        if self.first is None:
            self.first = value
            self.highest = 0
            self.ranges = [(0, 0)]
            self.unique = 1
            return 'start', 0
        position = (value - self.first) & U64_MASK
        if position >= (1 << 63):
            self.before_capture += 1
            return 'before_capture', 0
        index = bisect_right(self.ranges, (position, U64_MASK))
        if index and self.ranges[index - 1][1] >= position:
            self.duplicates += 1
            return 'duplicate', 0
        gap = 0
        if position > self.highest:
            gap = position - self.highest - 1
            status = 'gap' if gap else 'contiguous'
            self.highest = position
            self.forward_gap_observations += gap
        else:
            status = 'out_of_order'
            self.out_of_order += 1
        left = index > 0 and self.ranges[index - 1][1] + 1 == position
        right = index < len(self.ranges) and self.ranges[index][0] == position + 1
        if left and right:
            self.ranges[index - 1:index + 1] = [(self.ranges[index - 1][0], self.ranges[index][1])]
        elif left:
            self.ranges[index - 1] = (self.ranges[index - 1][0], position)
        elif right:
            self.ranges[index] = (position, self.ranges[index][1])
        else:
            self.ranges.insert(index, (position, position))
        self.unique += 1
        return status, gap

    def summary(self) -> dict[str, int | None]:
        return {'first_observed': self.first,
                'highest_observed': None if self.first is None else (self.first + self.highest) & U64_MASK,
                'unique_received': self.unique,
                'missing_observed_range': self.highest + 1 - self.unique,
                'forward_gap_observations': self.forward_gap_observations,
                'duplicates': self.duplicates, 'out_of_order': self.out_of_order,
                'before_capture': self.before_capture}


class ContinuityTracker:
    """Separate timelines per source address and epoch, preserve arrival order."""
    def __init__(self) -> None:
        self.streams: dict[tuple[str, int, int], tuple[SequenceTracker, SequenceTracker]] = {}
        self.previous_stream: tuple[str, int, int] | None = None
        self.previous_frame: int | None = None

    def observe(self, packet: Packet, source: tuple[str, int]) -> list[dict]:
        key = (source[0], source[1], packet.epoch)
        if key not in self.streams:
            self.streams[key] = (SequenceTracker(), SequenceTracker())
        packet_tracker, frame_tracker = self.streams[key]
        packet_status, packet_gap = packet_tracker.observe(packet.sequence)
        records = []
        for index, frame in enumerate(packet.frames):
            frame_status, frame_gap = frame_tracker.observe(frame.frame_id)
            continuous = (self.previous_stream == key and self.previous_frame is not None
                          and frame.frame_id == ((self.previous_frame + 1) & U64_MASK))
            records.append({'epoch': packet.epoch, 'packet_sequence': packet.sequence,
                            'flags': packet.flags, 'frame_id': frame.frame_id,
                            'record_in_packet': index, 'packet_status': packet_status,
                            'packet_gap_before': packet_gap, 'frame_status': frame_status,
                            'frame_gap_before': frame_gap, 'continuous_with_previous': continuous})
            self.previous_stream, self.previous_frame = key, frame.frame_id
        return records

    def summary(self) -> list[dict]:
        return [{'source_ip': key[0], 'source_port': key[1], 'epoch': key[2],
                 'packets': trackers[0].summary(), 'frames': trackers[1].summary()}
                for key, trackers in self.streams.items()]


def known_payload() -> bytes:
    """Independent fixed bytes with extreme signed samples and an intentional gap."""
    header = bytes.fromhex('4d313238 01 20 01 80 0000bb80 0003 0188 '
                           '0102030405060708 11223344 00000009')
    # Channels 0..3 = minimum, -1, zero, maximum, repeated through channel 127.
    pcm = bytes.fromhex('000080 ffffff 000000 ffff7f') * 32
    ids = (bytes.fromhex('0000000000000060'), bytes.fromhex('0000000000000061'),
           bytes.fromhex('0000000000000065'))
    return header + b''.join(frame_id + pcm for frame_id in ids)


def self_check() -> dict:
    packet = decode_payload(known_payload())
    assert packet.sequence == 0x0102030405060708 and packet.epoch == 0x11223344
    assert packet.flags == 9 and [f.frame_id for f in packet.frames] == [96, 97, 101]
    assert packet.frames[0].samples() == (-8388608, -1, 0, 8388607) * 32
    tracker = ContinuityTracker()
    records = tracker.observe(packet, ('192.168.10.2', 5000))
    assert [r['continuous_with_previous'] for r in records] == [False, True, False]
    assert records[-1]['frame_gap_before'] == 3
    return {'status': 'PASS', 'payload_bytes': PAYLOAD_BYTES, 'frame_ids': [96, 97, 101],
            'samples_checked': 128, 'missing_frames_preserved': 3}
