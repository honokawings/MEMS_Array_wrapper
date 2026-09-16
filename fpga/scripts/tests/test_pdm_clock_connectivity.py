"""PDM audit must cover physical replicas and all four output pads."""
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
    def test_one_shared_ff_covers_all_four_pads(self):
        rows = mod.microphone_launches(ff(0) + ''.join(pad(i, 'q0') for i in range(4)))
        self.assertEqual({r['launch_physical'] for r in rows}, {'FF0'})

    def test_all_physical_replicas_are_covered(self):
        rows = mod.microphone_launches(''.join(ff(i) + pad(i, f'q{i}') for i in range(4)))
        self.assertEqual({r['launch_physical'] for r in rows}, {f'FF{i}' for i in range(4)})

    def test_transparent_physical_buffer(self):
        buf = '    V_BUF \\BUF0 (\n            .Z (aliased),\n            .I (q0));\n'
        rows = mod.microphone_launches(ff(0) + buf + ''.join(pad(i, 'aliased') for i in range(4)))
        self.assertEqual(len(rows), 4)

    def test_missing_pad_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.microphone_launches(ff(0) + ''.join(pad(i, 'q0') for i in range(3)))

    def test_untraced_replica_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.microphone_launches(ff(0) + ''.join(pad(i, f'q{i}') for i in range(4)))

    def test_wrong_source_is_rejected(self):
        text = ff(0).replace('capture/mic_clk_dup0', 'unrelated_clock')
        with self.assertRaises(ValueError):
            mod.microphone_launches(text + ''.join(pad(i, 'q0') for i in range(4)))


if __name__ == '__main__':
    unittest.main()
