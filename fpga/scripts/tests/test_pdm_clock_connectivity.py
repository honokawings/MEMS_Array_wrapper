"""PDM audit must cover physical replicas and all eight output pads."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pdm_budget', Path(__file__).parents[1] / 'check_pdm_budget.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def ff(index):
    return (f'    V_FFASYN /* capture/mic_clk_dup{index}/FF */ #(\n'
            f'        .INIT(0))\n        \\FF{index} (\n'
            f'            .Q (q{index}),\n            .CK (audio_clk));\n')


def pad(index, source):
    return (f'    V_OBUFT /* mic_pad{index} */ #(\n'
            f'        .DRIVE_STRENGTH("8"))\n        \\PAD{index} (\n'
            f'            .O (mic_clk[{index}]),\n            .I ({source}),\n'
            f'            .T (1\'b0));\n')


class ClockConnectivity(unittest.TestCase):
    def test_input_group_accounts_for_real_key_port(self):
        report='Setup Summary(Slow Corner):\nasync_pad_ref audio122 1.200 0.000 0 65\nHold Summary'
        self.assertEqual(mod.input_budget(report,'slow','input selftest_key_n;'),(3.8,65))
        with self.assertRaises(ValueError):mod.input_budget(report,'slow','input another_pin;')
        with self.assertRaises(ValueError):mod.input_budget(report.replace(' 65',' 64'),'slow','input selftest_key_n;')

    def test_old_input_group_and_conservative_union(self):
        report='Setup Summary(Fast Corner):\nasync_pad_ref audio122 2.000 0.000 0 64\nHold Summary'
        self.assertEqual(mod.input_budget(report,'fast','input reset_n;'),(3.0,64))
        combined=report.replace('2.000','0.500').replace(' 64',' 65')
        bound,_=mod.input_budget(combined,'fast','input selftest_key_n;')
        self.assertGreaterEqual(bound,3.0)

    def test_input_group_rejects_missing_extra_and_violating_endpoints(self):
        report='Setup Summary(Slow Corner):\nasync_pad_ref audio122 1.200 0.000 0 65\nHold Summary'
        for bad in (report.replace(' 65',' 66'),report.replace('1.200','-0.001'),report.replace(' 0 65',' 1 65')):
            with self.assertRaises(ValueError):mod.input_budget(bad,'slow','input selftest_key_n;')

    def test_one_shared_ff_covers_all_eight_pads(self):
        rows = mod.microphone_launches(ff(0) + ''.join(pad(i, 'q0') for i in range(8)))
        self.assertEqual({r['launch_physical'] for r in rows}, {'FF0'})

    def test_all_physical_replicas_are_covered(self):
        rows = mod.microphone_launches(''.join(ff(i) + pad(i, f'q{i}') for i in range(8)))
        self.assertEqual({r['launch_physical'] for r in rows}, {f'FF{i}' for i in range(8)})

    def test_transparent_physical_buffer(self):
        buf = '    V_BUF \\BUF0 (\n            .Z (aliased),\n            .I (q0));\n'
        rows = mod.microphone_launches(ff(0) + buf + ''.join(pad(i, 'aliased') for i in range(8)))
        self.assertEqual(len(rows), 8)

    def test_missing_pad_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.microphone_launches(ff(0) + ''.join(pad(i, 'q0') for i in range(7)))

    def test_untraced_replica_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.microphone_launches(ff(0) + ''.join(pad(i, f'q{i}') for i in range(8)))

    def test_wrong_source_is_rejected(self):
        text = ff(0).replace('capture/mic_clk_dup0', 'unrelated_clock')
        with self.assertRaises(ValueError):
            mod.microphone_launches(text + ''.join(pad(i, 'q0') for i in range(8)))

    def test_replica_with_different_clock_is_rejected(self):
        text=''.join(ff(i)+pad(i,f'q{i}') for i in range(8))
        with self.assertRaises(ValueError):
            mod.microphone_launches(text.replace('.CK (audio_clk)', '.CK (other_clk)',1))

    def test_replica_with_different_initial_state_is_rejected(self):
        text=''.join(ff(i)+pad(i,f'q{i}') for i in range(8))
        with self.assertRaises(ValueError):
            mod.microphone_launches(text.replace('.INIT(0)', '.INIT(1)',1))


if __name__ == '__main__':
    unittest.main()
