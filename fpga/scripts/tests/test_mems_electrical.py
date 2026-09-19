"""Board voltage mismatch must fail before PDS or pin-file replacement."""
import importlib.util
from pathlib import Path
import sys
import re
import tempfile
import unittest
from unittest.mock import patch
SCRIPT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SCRIPT))
import build

class MemsElectrical(unittest.TestCase):
    def test_clock_bank_18v(self):
        for pin in ('AC26','AB26','U25','AA24','AB25','U26','Y25','AA25'):
            self.assertEqual(build.microphone_electrical('mic_clk[0]',pin),('1.8','LVCMOS18'))
    def test_l6_data_18v(self):
        self.assertEqual(build.microphone_electrical('pdm_data[0]','U25'),('1.8','LVCMOS18'))
    def test_l5_direct_input_rejected(self):
        with self.assertRaisesRegex(ValueError,'fixed 3.3 V'):
            build.microphone_electrical('pdm_data[0]','P19')
    def test_l5_translated_input_requires_explicit_profile(self):
        self.assertEqual(build.microphone_electrical('pdm_data[0]','P19',True),('3.3','LVCMOS33'))
    def test_l5_clock_rejected_even_with_input_translators(self):
        with self.assertRaises(ValueError):build.microphone_electrical('mic_clk[0]','P19',True)
    def test_other_bank_rejected(self):
        with self.assertRaises(ValueError):build.microphone_electrical('pdm_data[0]','D18')
    def test_package_banks_are_disjoint(self):
        self.assertEqual(sum(len(x.split()) for x in build.MIC_BANK_PINS.values()),len(build.MIC_PIN_BANK))

    def test_direct_l5_failure_preserves_existing_pin_file(self):
        readme=(build.ROOT/'README.md').read_text(encoding='utf8')
        readme=re.sub(r'\b[A-Z]{1,2}\d+\s*-\s*DATA0\b','P19-DATA0',readme)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'README.md').write_text(readme,encoding='utf8')
            pins=root/'fpga/constraints/board_pins.fdc';pins.parent.mkdir(parents=True)
            pins.write_text('old constraints')
            with patch.object(build,'ROOT',root),self.assertRaises(ValueError):build.prepare_pins()
            self.assertEqual(pins.read_text(),'old constraints')

    def test_translated_profile_has_eight_strong_18v_clocks(self):
        readme=(build.ROOT/'README.md').read_text(encoding='utf8')
        readme=re.sub(r'\b[A-Z]{1,2}\d+\s*-\s*DATA0\b','P19-DATA0',readme)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'README.md').write_text(readme,encoding='utf8')
            with patch.object(build,'ROOT',root):mapping=build.prepare_pins(True)
            self.assertEqual(len(mapping),99)
            fdc=(root/'fpga/constraints/board_pins.fdc').read_text()
            for i in range(8):
                for attr,value in [('VCCIO','1.8'),('STANDARD','LVCMOS18'),('DRIVE','16'),('SLEW','FAST')]:
                    self.assertIn(f'define_attribute {{p:mic_clk[{i}]}} {{PAP_IO_{attr}}} {{{value}}}',fdc)

    def test_current_direct_18v_map(self):
        readme=(build.ROOT/'README.md').read_text(encoding='utf8')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'README.md').write_text(readme,encoding='utf8')
            with patch.object(build,'ROOT',root):mapping=build.prepare_pins()
            self.assertEqual(len(mapping),99)
            mic_ports={p:pin for p,pin in mapping.items() if p.startswith(('pdm_data','mic_clk'))}
            self.assertEqual(len(mic_ports),72)
            self.assertTrue(all(build.MIC_PIN_BANK[pin] in ('L6','L7') for pin in mic_ports.values()))
            self.assertEqual({p:build.MIC_PIN_BANK[pin] for p,pin in mic_ports.items() if p.startswith('mic_clk')},
                             {f'mic_clk[{i}]':'L6' for i in range(8)})

if __name__=='__main__':unittest.main()
