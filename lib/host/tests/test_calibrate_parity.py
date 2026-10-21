"""Independent capture fixtures for parity estimation, exclusions and provenance."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calibrate_parity import capture_statistics,estimate,main


def write_capture(prefix: Path,amplitude: int,ratio: float=2.0,clip: bool=False,flag: int=0,frames: int=2048):
    with Path(str(prefix)+'.pcm24le').open('wb') as pcm,Path(str(prefix)+'.frames.jsonl').open('w') as metadata:
        for n in range(frames):
            sine=math.sin(2*math.pi*n/48)
            samples=[int(round((c-64)*100+amplitude*(ratio if c%2 else 1)*sine)) for c in range(128)]
            if clip and n==500:samples[3]=(1 << 23)-1
            pcm.write(b''.join(x.to_bytes(3,'little',signed=True) for x in samples))
            metadata.write(json.dumps({'byte_offset':n*384,'source_ip':'192.168.10.2','source_port':5000,
                                       'epoch':1,'frame_id':96+n,'flags':flag,'frame_status':'start' if n==0 else 'contiguous'})+'\n')


class ParityCalibrationTests(unittest.TestCase):
    def test_known_gain_and_dc_in_real_capture_format(self):
        with tempfile.TemporaryDirectory() as folder:
            tone=Path(folder)/'tone';quiet=Path(folder)/'quiet'
            write_capture(tone,100000);write_capture(quiet,0)
            t=capture_statistics(tone);q=capture_statistics(quiet)
            result=estimate(t,q)
            self.assertEqual(result['status'],'PASS');self.assertEqual(result['valid_pairs'],64)
            self.assertEqual(result['even_gain_q22'],1 << 22)
            self.assertLess(abs(result['odd_gain_q22']-(1 << 21)),5)
            self.assertLess(result['maximum_predicted_pair_residual_db'],0.0001)
            self.assertFalse(result['hardware_configured'])
            output=Path(folder)/'proposal.json'
            self.assertEqual(main(['--tone',str(tone),'--silence',str(quiet),'--output',str(output),'--known-common-field']),0)
            self.assertTrue(json.loads(output.read_text())['declared_assumptions']['unity_parity_and_channel_gains'])

    def test_clipped_pair_is_excluded_not_calibrated(self):
        with tempfile.TemporaryDirectory() as folder:
            tone=Path(folder)/'tone';quiet=Path(folder)/'quiet'
            write_capture(tone,100000,clip=True);write_capture(quiet,0)
            t=capture_statistics(tone);q=capture_statistics(quiet)
            with self.assertRaises(ValueError):estimate(t,q)
            r=estimate(t,q,minimum_pairs=63)
            self.assertFalse(r['pairs'][1]['accepted']);self.assertEqual(r['valid_pairs'],63)
            self.assertEqual(t['skipped']['full_scale_samples'],1)

    def test_noise_only_and_selftest_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            tone=Path(folder)/'tone';quiet=Path(folder)/'quiet';bist=Path(folder)/'bist'
            write_capture(tone,1000);write_capture(quiet,1000);write_capture(bist,100000,flag=16)
            with self.assertRaises(ValueError):estimate(capture_statistics(tone),capture_statistics(quiet))
            with self.assertRaises(ValueError):capture_statistics(bist)

    def test_metadata_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix=Path(folder)/'capture';write_capture(prefix,100000)
            meta=Path(str(prefix)+'.frames.jsonl');lines=meta.read_text().splitlines()
            row=json.loads(lines[500]);row['byte_offset']+=1;lines[500]=json.dumps(row);meta.write_text('\n'.join(lines)+'\n')
            with self.assertRaises(ValueError):capture_statistics(prefix)

    def test_compensation_direction_and_pair_residual(self):
        quiet={'variance_pcm':[0]*128,'clipped_channels':[]}
        tone={'variance_pcm':[10**10*(0.5**2 if c%2 else 1) for c in range(128)],'clipped_channels':[]}
        result=estimate(tone,quiet)
        self.assertEqual(result['even_gain_q22'],1 << 21);self.assertEqual(result['odd_gain_q22'],1 << 22)
        tone['variance_pcm'][5]=10**10*0.7**2
        self.assertEqual(estimate(tone,quiet)['status'],'NEEDS_PER_CHANNEL_CALIBRATION')


if __name__=='__main__':unittest.main()
