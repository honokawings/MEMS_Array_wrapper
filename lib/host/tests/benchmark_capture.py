"""Measure parsing + PCM/JSONL writing throughput, without a network claim."""
import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcm_protocol import known_payload
from receive_pcm import CaptureWriter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packets', type=int, default=16000)
    args = parser.parse_args()
    if args.packets <= 0:
        parser.error('--packets must be positive')
    with tempfile.TemporaryDirectory(prefix='m128_capture_benchmark_') as folder:
        writer = CaptureWriter(Path(folder) / 'benchmark')
        template = bytearray(known_payload())
        started = time.perf_counter()
        for sequence in range(args.packets):
            struct.pack_into('>Q', template, 16, sequence)
            for record in range(3):
                struct.pack_into('>Q', template, 32 + 392 * record, 96 + 3 * sequence + record)
            writer.write(bytes(template), ('192.168.10.2', 5000), sequence * 62500)
        summary = writer.close()
        elapsed = time.perf_counter() - started
        if summary['streams'][0]['frames']['missing_observed_range'] != 0:
            raise AssertionError('benchmark introduced a frame gap')
        pcm_bytes = writer.pcm_path.stat().st_size
        metadata_bytes = writer.frames_path.stat().st_size
        print(json.dumps({'packets': args.packets, 'frames': summary['saved_frames'],
                          'elapsed_seconds': elapsed, 'packets_per_second': args.packets / elapsed,
                          'required_packets_per_second': 16000, 'pcm_bytes': pcm_bytes,
                          'metadata_bytes': metadata_bytes,
                          'scope': 'decode + continuity + buffered file writes + close; excludes network and fsync durability'}, indent=2))


if __name__ == '__main__':
    main()
