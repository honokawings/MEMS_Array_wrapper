"""BIST extension, numeric corruption, delivery gaps, capture and metadata."""
import json,struct,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pcm_protocol import decode_payload,ProtocolError
from verify_selftest import SelftestVerifier,verify_capture
from receive_pcm import CaptureWriter


def payload(seq=0,epoch=1,first=96,flags=16):
    data=SelftestVerifier().oracle
    return struct.pack('>4sBBBBIHHQII',b'M128',1,32,1,128,48000,3,392,seq,epoch,flags)+b''.join(
        struct.pack('>Q',f)+data[(f%16)*384:(f%16+1)*384] for f in range(first,first+3))


class SelftestTests(unittest.TestCase):
    def test_extension_and_period(self):
        v=SelftestVerifier()
        for seq in range(32):v.observe(decode_payload(payload(seq,first=96+seq*3)))
        r=v.result(96)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['samples_compared'],12288)
        self.assertEqual(decode_payload(payload()).flag_names,['selftest_data'])
        for flags in (32,64,0x80000000):
            with self.assertRaises(ProtocolError):decode_payload(payload(flags=flags))

    def test_errors_are_not_pass(self):
        for kind in ('data','channel','phase','flags','gap','duplicate','no_test','short'):
            with self.subTest(kind=kind):
                v=SelftestVerifier()
                for seq in range(16):
                    p=bytearray(payload(seq,first=96+seq*3))
                    if seq==5:
                        if kind=='data':p[123]^=1
                        if kind=='channel':p[40:43],p[43:46]=p[43:46],p[40:43]
                        if kind=='phase':p=bytearray(payload(seq,first=113))
                        if kind=='flags':p[31]=48
                        if kind=='gap':continue
                        if kind=='duplicate':v.observe(decode_payload(p))
                    if kind=='no_test':p[31]=0
                    v.observe(decode_payload(p))
                self.assertEqual(v.result(49 if kind=='short' else 48)['status'],'FAIL')

    def test_capture_file_and_arrival_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder)/'bist';writer=CaptureWriter(prefix)
            for seq in range(16):writer.write(payload(seq,first=96+seq*3),('192.168.10.2',5000),10**9+seq*62500)
            summary=writer.close()
            self.assertEqual(summary['selftest_packets'],16)
            self.assertEqual(summary['flagged_packets'],0)
            r=verify_capture(prefix,48)
            self.assertEqual(r['status'],'PASS')
            self.assertEqual(r['arrival_rates'][0]['packets_per_second'],16000)
            self.assertTrue(json.loads(Path(str(prefix)+'.frames.jsonl').read_text().splitlines()[0])['selftest'])
            with Path(str(prefix)+'.pcm24le').open('r+b') as f:f.seek(200);f.write(b'\xff\xff\xff')
            self.assertEqual(verify_capture(prefix,48)['status'],'FAIL')

    def test_truncated_and_wrong_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder)/'bist';writer=CaptureWriter(prefix)
            writer.write(payload(),('192.168.10.2',5000),10**9);writer.close()
            path=Path(str(prefix)+'.frames.jsonl')
            lines=path.read_text().splitlines();row=json.loads(lines[1]);row['flags']=0
            lines[1]=json.dumps(row);path.write_text('\n'.join(lines)+'\n')
            with self.assertRaises(ProtocolError):verify_capture(prefix,48)


if __name__=='__main__':unittest.main()
