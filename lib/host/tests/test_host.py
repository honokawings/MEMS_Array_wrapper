"""Run: python -m unittest discover -s lib/host/tests -v"""
from __future__ import annotations

import json
from pathlib import Path
import random
import socket
import struct
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcm_protocol import (ContinuityTracker, ProtocolError, SequenceTracker,
                          decode_payload, known_payload, self_check)
from receive_pcm import CaptureWriter, capture, check_file


def packet_bytes(sequence=0, epoch=1, frame_ids=(96, 97, 98), flags=0):
    # Test-side independent struct assembly, with channel/record-varying values.
    result = struct.pack('>4sBBBBIHHQII', b'M128', 1, 32, 1, 128, 48000, 3, 392,
                         sequence, epoch, flags)
    for record, frame_id in enumerate(frame_ids):
        result += struct.pack('>Q', frame_id)
        for channel in range(128):
            sample = (record * 1000 + channel * 73021) % (1 << 24) - (1 << 23)
            result += sample.to_bytes(3, 'little', signed=True)
    return result


class ProtocolTests(unittest.TestCase):
    def test_fixed_known_bytes(self):
        self.assertEqual(self_check()['status'], 'PASS')
        self.assertEqual(decode_payload(known_payload()).flag_names,
                         ['saturation', 'packetizer_framing_error'])

    def test_every_sample(self):
        result = decode_payload(packet_bytes(sequence=(1 << 64) - 1, epoch=0xFFFFFFFF, flags=15))
        for record, frame in enumerate(result.frames):
            expected = tuple((record * 1000 + c * 73021) % (1 << 24) - (1 << 23) for c in range(128))
            self.assertEqual(frame.samples(), expected)
        self.assertEqual(result.sequence, (1 << 64) - 1)
        self.assertEqual(result.epoch, 0xFFFFFFFF)

    def test_strict_invalid_headers(self):
        original = packet_bytes()
        for offset in (0, 4, 5, 6, 7, 8, 12, 14, 28):
            data = bytearray(original)
            data[offset] ^= 0x10
            with self.subTest(offset=offset), self.assertRaises(ProtocolError):
                decode_payload(bytes(data))
        for data in (b'', original[:-1], original + b'\0'):
            with self.assertRaises(ProtocolError):
                decode_payload(data)

    def test_sequence_gap_fills_duplicates_and_wrap(self):
        tracker = SequenceTracker()
        observed = [tracker.observe(n) for n in (10, 13, 11, 13, 12, 9)]
        self.assertEqual(observed, [('start', 0), ('gap', 2), ('out_of_order', 0),
                                    ('duplicate', 0), ('out_of_order', 0), ('before_capture', 0)])
        self.assertEqual(tracker.summary()['missing_observed_range'], 0)
        self.assertEqual(tracker.summary()['duplicates'], 1)
        self.assertEqual(tracker.summary()['out_of_order'], 2)
        wrap = SequenceTracker()
        self.assertEqual([wrap.observe(n) for n in ((1 << 64) - 2, (1 << 64) - 1, 0, 2, 1)],
                         [('start', 0), ('contiguous', 0), ('contiguous', 0), ('gap', 1), ('out_of_order', 0)])
        self.assertEqual(wrap.summary()['highest_observed'], 2)
        self.assertEqual(wrap.summary()['missing_observed_range'], 0)

    def test_interval_tracker_against_independent_set(self):
        rng = random.Random(3497)
        values = list(range(1, 1000))
        rng.shuffle(values)
        values += values[:100]
        tracker = SequenceTracker()
        tracker.observe(100)
        seen = {0}
        for value in values:
            status, _ = tracker.observe(100 + value)
            self.assertEqual(status == 'duplicate', value in seen)
            seen.add(value)
            self.assertEqual(tracker.summary()['missing_observed_range'], max(seen) + 1 - len(seen))
        self.assertEqual(tracker.ranges, [(0, 999)])

    def test_epochs_and_arrival_continuity(self):
        tracker = ContinuityTracker()
        source = ('192.168.10.2', 5000)
        first = tracker.observe(decode_payload(packet_bytes(0, 1, (96, 97, 101))), source)
        self.assertEqual([x['continuous_with_previous'] for x in first], [False, True, False])
        self.assertEqual(first[2]['frame_gap_before'], 3)
        changed = tracker.observe(decode_payload(packet_bytes(0, 2, (102, 103, 104))), source)
        self.assertFalse(changed[0]['continuous_with_previous'])
        self.assertEqual(len(tracker.summary()), 2)
        old = tracker.observe(decode_payload(packet_bytes(1, 1, (98, 99, 100))), source)
        self.assertEqual(old[0]['frame_status'], 'out_of_order')
        self.assertFalse(old[0]['continuous_with_previous'])
        self.assertTrue(old[1]['continuous_with_previous'])
        self.assertEqual(tracker.summary()[0]['frames']['missing_observed_range'], 0)

    def test_binary_and_hex_check(self):
        with tempfile.TemporaryDirectory() as folder:
            binary, text = Path(folder) / 'payload.bin', Path(folder) / 'payload.hex'
            binary.write_bytes(known_payload() * 2)
            text.write_text('// RTL dump\n' + known_payload().hex(' ') + ' # payload\n', encoding='ascii')
            self.assertEqual(check_file(binary)['packets'], 2)
            self.assertEqual(check_file(text)['frames'], 3)
            binary.write_bytes(b'bad')
            with self.assertRaises(ProtocolError):
                check_file(binary)

    def test_golden_comparison_rejects_corrupted_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            binary, golden = Path(folder) / 'payload.bin', Path(folder) / 'golden.bin'
            payload = packet_bytes(frame_ids=(0, 1, 2))
            packet = decode_payload(payload)
            golden.write_bytes(b''.join(sample.to_bytes(4, 'little', signed=True)
                                        for frame in packet.frames for sample in frame.samples()))
            binary.write_bytes(payload)
            self.assertEqual(check_file(binary, golden)['samples_compared'], 384)
            corrupt = bytearray(payload)
            corrupt[40] ^= 1
            binary.write_bytes(corrupt)
            with self.assertRaisesRegex(ProtocolError, 'frame=0 channel=0'):
                check_file(binary, golden)

    def test_capture_exact_pcm_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder) / 'capture'
            payloads = [packet_bytes(0, 3, (96, 97, 101), 2),
                        packet_bytes(2, 3, (105, 106, 107)),
                        packet_bytes(1, 3, (102, 103, 104)),
                        packet_bytes(1, 3, (102, 103, 104)),
                        packet_bytes(0, 4, (96, 97, 98))]
            writer = CaptureWriter(prefix)
            for index, payload in enumerate(payloads):
                writer.write(payload, ('192.168.10.2', 5000), index)
            report = writer.close()
            expected = b''.join(frame.pcm for payload in payloads for frame in decode_payload(payload).frames)
            self.assertEqual(Path(str(prefix) + '.pcm24le').read_bytes(), expected)
            metadata = [json.loads(line) for line in Path(str(prefix) + '.frames.jsonl').read_text().splitlines()]
            self.assertEqual(len(metadata), 15)
            self.assertEqual([record['byte_offset'] for record in metadata], list(range(0, 15 * 384, 384)))
            self.assertEqual(metadata[2]['frame_id'], 101)
            self.assertFalse(metadata[2]['continuous_with_previous'])
            self.assertEqual(metadata[6]['packet_status'], 'out_of_order')
            self.assertEqual(metadata[9]['packet_status'], 'duplicate')
            self.assertEqual(report['streams'][0]['packets']['missing_observed_range'], 0)
            self.assertEqual(report['streams'][0]['frames']['missing_observed_range'], 3)
            self.assertFalse(report['gaps_filled'])
            self.assertEqual(report['saved_pcm_bytes'], 15 * 384)
            self.assertEqual(json.loads(Path(str(prefix) + '.summary.json').read_text())['saved_frames'], 15)
            with self.assertRaises(FileExistsError):
                CaptureWriter(prefix)
            self.assertEqual(Path(str(prefix) + '.pcm24le').read_bytes(), expected)

    def test_rtl_end_to_end_fixture_against_cmodel(self):
        root = Path(__file__).resolve().parents[3]
        fixture = root / 'log/net_core/payloads.hex'
        golden = root / 'tb/vectors/expected_pcm.bin'
        if not fixture.exists() or not golden.exists():
            self.skipTest('run full network-core RTL simulation and model vectors first')
        result = check_file(fixture, golden)
        self.assertEqual(result['packets'], 99)
        self.assertEqual(result['samples_compared'], 38016)
        self.assertEqual([entry['epoch'] for entry in result['streams']], [1, 2])
        self.assertEqual([entry['packets']['unique_received'] for entry in result['streams']], [53, 46])
        self.assertEqual([entry['frames']['missing_observed_range'] for entry in result['streams']], [0, 17])
        self.assertEqual([entry['frames']['highest_observed'] for entry in result['streams']], [254, 250])
        self.assertTrue(all(flags in (0, 1, 2, 3) for flags in result['packet_flag_counts']))
        self.assertTrue(any(flags & 2 for flags in result['packet_flag_counts']))

    def test_udp_loopback_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder) / 'loopback'
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as temporary:
                temporary.bind(('127.0.0.1', 0))
                port = temporary.getsockname()[1]
            args = SimpleNamespace(output=prefix, receive_buffer=1024 * 1024, bind='127.0.0.1', port=port,
                                   queue_packets=32, source_ip='127.0.0.1', source_port=0, seconds=5, packets=7)
            result, errors = [], []

            def run():
                try:
                    result.append(capture(args))
                except BaseException as exc:
                    errors.append(exc)
            runner = threading.Thread(target=run, daemon=True)
            runner.start()
            deadline = time.monotonic() + 3
            while not Path(str(prefix) + '.pcm24le').exists() and time.monotonic() < deadline and runner.is_alive():
                time.sleep(0.01)
            self.assertTrue(Path(str(prefix) + '.pcm24le').exists(), errors)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(b'invalid', ('127.0.0.1', port))
                for sequence in (0, 2, 1, 1, 3, 4):
                    sender.sendto(packet_bytes(sequence, 7, tuple(96 + sequence * 3 + i for i in range(3))),
                                  ('127.0.0.1', port))
            runner.join(timeout=7)
            self.assertFalse(runner.is_alive())
            self.assertFalse(errors)
            self.assertEqual(result[0]['saved_packets'], 6)
            self.assertEqual(result[0]['capture']['invalid_payload_packets'], 1)
            self.assertEqual(result[0]['capture']['host_queue_dropped_packets'], 0)
            self.assertEqual(result[0]['streams'][0]['packets']['duplicates'], 1)
            self.assertEqual(result[0]['streams'][0]['packets']['missing_observed_range'], 0)
            self.assertEqual(Path(str(prefix) + '.pcm24le').stat().st_size, 6 * 3 * 384)


if __name__ == '__main__':
    unittest.main()
