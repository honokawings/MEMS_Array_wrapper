"""M128 UDP capture: python lib/host/receive_pcm.py --help (stdlib only)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time

try:
    from .pcm_protocol import (CHANNELS, ENCODING, PAYLOAD_BYTES, PCM_FRAME_BYTES, SAMPLE_RATE,
                               ContinuityTracker, ProtocolError, decode_payload, self_check)
except ImportError:
    from pcm_protocol import (CHANNELS, ENCODING, PAYLOAD_BYTES, PCM_FRAME_BYTES, SAMPLE_RATE,
                              ContinuityTracker, ProtocolError, decode_payload, self_check)


class CaptureWriter:
    """Append raw frames and one JSONL record per raw frame, no silent filling."""
    def __init__(self, prefix: Path) -> None:
        self.prefix = Path(prefix)
        self.pcm_path = Path(str(prefix) + '.pcm24le')
        self.frames_path = Path(str(prefix) + '.frames.jsonl')
        self.summary_path = Path(str(prefix) + '.summary.json')
        for path in (self.pcm_path, self.frames_path, self.summary_path):
            if path.exists():
                raise FileExistsError(f'output already exists: {path}')
        self.prefix.parent.mkdir(parents=True, exist_ok=True)
        self.pcm_file = self.pcm_path.open('xb', buffering=1024 * 1024)
        try:
            self.frames_file = self.frames_path.open('x', encoding='utf-8', buffering=1024 * 1024)
        except BaseException:
            self.pcm_file.close()
            raise
        self.tracker = ContinuityTracker()
        self.packet_count = 0
        self.frame_count = 0
        self.flagged_packets = 0
        self.selftest_packets = 0
        self.closed = False

    def write(self, payload: bytes, source: tuple[str, int], arrival_ns: int) -> None:
        packet = decode_payload(payload)
        records = self.tracker.observe(packet, source)
        raw = b''.join(frame.pcm for frame in packet.frames)
        lines = []
        for index, record in enumerate(records):
            record.update({'byte_offset': (self.frame_count + index) * PCM_FRAME_BYTES,
                           'source_ip': source[0], 'source_port': source[1], 'arrival_monotonic_ns': arrival_ns})
            lines.append(json.dumps(record, separators=(',', ':')) + '\n')
        self.pcm_file.write(raw)
        self.frames_file.write(''.join(lines))
        self.packet_count += 1
        self.frame_count += 3
        self.flagged_packets += bool(packet.flags & 0x2F)
        self.selftest_packets += bool(packet.flags & 0x10)

    def close(self, capture_stats: dict | None = None) -> dict:
        if self.closed:
            raise RuntimeError('capture already closed')
        self.closed = True
        try:
            self.pcm_file.close()
        finally:
            self.frames_file.close()
        report = {'format': 'M128 capture v1', 'encoding': ENCODING, 'sample_rate_hz': SAMPLE_RATE,
                  'channels': CHANNELS, 'pcm_frame_bytes': PCM_FRAME_BYTES,
                  'pcm_file': self.pcm_path.name, 'metadata_file': self.frames_path.name,
                  'saved_packets': self.packet_count, 'saved_frames': self.frame_count,
                  'saved_pcm_bytes': self.frame_count * PCM_FRAME_BYTES,
                  'flagged_packets': self.flagged_packets, 'selftest_packets': self.selftest_packets,
                  'streams': self.tracker.summary(),
                  'arrival_order_preserved': True, 'gaps_filled': False,
                  'os_socket_drop_count': None,
                  'missing_count_scope': 'first observed through highest observed per source/epoch; reordered arrivals close gaps',
                  'capture': capture_stats or {}}
        with self.summary_path.open('x', encoding='utf-8') as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write('\n')
        return report


def check_file(path: Path, golden_path: Path | None = None) -> dict:
    if path.suffix.lower() in ('.hex', '.mem', '.txt'):
        lines = (line.split('//')[0].split('#')[0] for line in path.read_text(encoding='ascii').splitlines())
        data = bytes.fromhex(' '.join(lines))
    else:
        data = path.read_bytes()
    if not data or len(data) % PAYLOAD_BYTES:
        raise ProtocolError(f'{path}: expected one or more concatenated {PAYLOAD_BYTES}-byte UDP payloads')
    tracker = ContinuityTracker()
    count = 0
    flag_counts: Counter = Counter()
    golden = golden_path.read_bytes() if golden_path is not None else None
    samples_compared = 0
    if golden is not None and (not golden or len(golden) % (CHANNELS * 4)):
        raise ProtocolError('golden PCM must contain complete 128-channel frames of little-endian signed 32-bit samples')
    for offset in range(0, len(data), PAYLOAD_BYTES):
        packet = decode_payload(data[offset:offset + PAYLOAD_BYTES])
        tracker.observe(packet, ('file', 0))
        flag_counts[packet.flags] += 1
        if golden is not None:
            for frame in packet.frames:
                start = frame.frame_id * CHANNELS * 4
                if start + CHANNELS * 4 > len(golden):
                    raise ProtocolError(f'frame_id {frame.frame_id} is outside golden PCM array')
                for channel, actual in enumerate(frame.samples()):
                    address = start + channel * 4
                    expected = int.from_bytes(golden[address:address + 4], 'little', signed=True)
                    if actual != expected:
                        raise ProtocolError(f'golden mismatch: epoch={packet.epoch} packet={packet.sequence} '
                                            f'frame={frame.frame_id} channel={channel}: {actual} != {expected}')
                    samples_compared += 1
        count += 1
    result = {'status': 'PASS', 'file': str(path), 'payload_bytes': len(data),
              'payload_sha256': hashlib.sha256(data).hexdigest(),
              'packets': count, 'frames': count * 3, 'packet_flag_counts': dict(flag_counts),
              'streams': tracker.summary()}
    if golden is not None:
        result.update({'golden_file': str(golden_path), 'golden_sha256': hashlib.sha256(golden).hexdigest(),
                       'samples_compared': samples_compared})
    return result


def capture(args: argparse.Namespace) -> dict:
    prefix = args.output or Path('capture_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    # Bind before creating files, so a busy port does not create empty captures.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    writer = None
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, args.receive_buffer)
        sock.bind((args.bind, args.port))
        sock.settimeout(0.25)
        actual_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        writer = CaptureWriter(prefix)
        pending: queue.Queue = queue.Queue(maxsize=args.queue_packets)
        finished = threading.Event()
        worker_errors: list[BaseException] = []
        stats = {'started_utc': datetime.now(timezone.utc).isoformat(), 'bind': args.bind, 'port': args.port,
                 'source_ip_filter': args.source_ip, 'source_port_filter': args.source_port,
                 'socket_receive_buffer_bytes': actual_buffer, 'queue_capacity_packets': args.queue_packets,
                 'socket_received_packets': 0, 'source_filtered_packets': 0,
                 'host_queue_dropped_packets': 0, 'invalid_payload_packets': 0,
                 'invalid_payload_examples': [], 'stop_reason': 'running'}

        def consume() -> None:
            try:
                while not finished.is_set() or not pending.empty():
                    try:
                        payload, address, received = pending.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        writer.write(payload, address, received)
                    except ProtocolError as exc:
                        stats['invalid_payload_packets'] += 1
                        if len(stats['invalid_payload_examples']) < 10:
                            stats['invalid_payload_examples'].append(str(exc))
                    finally:
                        pending.task_done()
            except BaseException as exc:
                worker_errors.append(exc)
                finished.set()

        worker = threading.Thread(target=consume, name='pcm-file-writer', daemon=True)
        worker.start()
        started = last_status = time.monotonic()
        print(f'Listening {args.bind}:{args.port}; output {prefix}; socket buffer {actual_buffer} bytes', file=sys.stderr)
        receive_error = None
        try:
            while not finished.is_set():
                if args.seconds and time.monotonic() - started >= args.seconds:
                    stats['stop_reason'] = 'duration_limit'
                    break
                if args.packets and stats['socket_received_packets'] >= args.packets:
                    stats['stop_reason'] = 'packet_limit'
                    break
                try:
                    payload, address = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                received = time.monotonic_ns()
                stats['socket_received_packets'] += 1
                if ((args.source_ip != 'any' and address[0] != args.source_ip)
                        or (args.source_port and address[1] != args.source_port)):
                    stats['source_filtered_packets'] += 1
                    continue
                try:
                    pending.put_nowait((payload, address, received))
                except queue.Full:
                    stats['host_queue_dropped_packets'] += 1
                if time.monotonic() - last_status >= 2:
                    print(f'received={stats["socket_received_packets"]} saved={writer.packet_count} '
                          f'queue_dropped={stats["host_queue_dropped_packets"]} '
                          f'invalid={stats["invalid_payload_packets"]}', file=sys.stderr)
                    last_status = time.monotonic()
        except KeyboardInterrupt:
            stats['stop_reason'] = 'keyboard_interrupt'
        except BaseException as exc:
            receive_error = exc
            stats['stop_reason'] = 'receive_error'
            stats['error'] = repr(exc)
        finally:
            sock.close()
            finished.set()
            worker.join()
        if worker_errors:
            stats['stop_reason'] = 'write_error'
            stats['error'] = repr(worker_errors[0])
        stats['queued_packets_not_saved'] = pending.qsize()
        stats['elapsed_seconds'] = round(time.monotonic() - started, 6)
        report = writer.close(stats)
        if worker_errors:
            raise RuntimeError(f'capture write failed; inspect {writer.summary_path}') from worker_errors[0]
        if receive_error:
            raise RuntimeError(f'capture receive failed; inspect {writer.summary_path}') from receive_error
        return report
    finally:
        sock.close()
        if writer is not None and not writer.closed:
            writer.close({'stop_reason': 'startup_error'})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', nargs='?', const='self', metavar='PAYLOAD_FILE',
                        help='run fixed known-byte self-check, or validate binary/hex RTL UDP payload dump')
    parser.add_argument('--golden', type=Path,
                        help='with --check FILE, compare records by frame_id to 128-channel little-endian int32 golden frames')
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--source-ip', default='192.168.10.2', help='source IPv4 filter, or any')
    parser.add_argument('--source-port', type=int, default=5000, help='source UDP port; 0 allows any')
    parser.add_argument('--output', type=Path, help='new output prefix; existing captures are never overwritten')
    parser.add_argument('--seconds', type=float, default=0, help='0 means until Ctrl+C')
    parser.add_argument('--packets', type=int, default=0, help='stop after this many received UDP datagrams; 0 means unlimited')
    parser.add_argument('--receive-buffer', type=int, default=8 * 1024 * 1024)
    parser.add_argument('--queue-packets', type=int, default=8192)
    args = parser.parse_args(argv)
    if args.golden and (not args.check or args.check == 'self'):
        parser.error('--golden requires --check PAYLOAD_FILE')
    if not (0 < args.port < 65536 and 0 <= args.source_port < 65536):
        parser.error('ports must be 1..65535; source-port also accepts 0')
    if args.seconds < 0 or args.packets < 0 or args.receive_buffer <= 0 or args.queue_packets <= 0:
        parser.error('limits must be nonnegative; buffers must be positive')
    try:
        result = (self_check() if args.check == 'self' else check_file(Path(args.check), args.golden)) if args.check else capture(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
