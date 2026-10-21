"""Synthetic physical parser probes; these fixtures are not FPGA timing evidence."""
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SCRIPTS))
import check_i2s_budget as i2s


class I2SPhysicalBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.paths={k:self.root/(k+'.txt') for k in ('timing_report','constraints','rtl','slow_sdf','slow_netlist','fast_sdf','fast_netlist')}
        self.paths['constraints'].write_text((SCRIPTS.parent/'constraints/timing.fdc').read_text())
        self.paths['rtl'].write_text((SCRIPTS.parents[1]/'rtl/audio/pcm_i2s_tx.sv').read_text())
        self.paths['timing_report'].write_text('Fixture only\nDesign Summary : All Constraints Met.\nclock uncertainty -0.300\n')
        cells=['V_USCM #(.USCM_MODE("BUF_A")) \\audio_buffer (.CLKOUT(audio_net), .CLK0(pll_net));']
        sdf_cells=[]
        for port in (*i2s.PORTS,'mic_clk[0]'):
            tag=port.replace('[','_').replace(']','')
            cells.append(f"V_FFSYN #(.INIT(1'b0)) \\{tag}_ff (.Q({tag}_net), .CK(audio_net), .D(next_value), .CE(1'b1), .SR(reset));")
            cells.append(f"V_OBUFT \\{tag}_pad (.O({port}), .I({tag}_net), .T(1'b0));")
            sdf_cells.extend([f'(CELL (CELLTYPE "V_FFSYN") (INSTANCE {tag}_ff) (DELAY (ABSOLUTE (PORT CK (100) (100)) (IOPATH CK Q (200) (200)))))',
                              f'(CELL (CELLTYPE "V_OBUFT") (INSTANCE {tag}_pad) (DELAY (ABSOLUTE (PORT I (400) (400)) (IOPATH I O (50) (50)))))'])
        self.netlist='\n'.join(cells)
        for corner in ('slow','fast'):
            self.paths[corner+'_netlist'].write_text(self.netlist)
            self.paths[corner+'_sdf'].write_text('// '+corner.title()+' Corner\n(DELAYFILE (TIMESCALE 1 ps)\n'+'\n'.join(sdf_cells)+'\n)')

    def result(self):return i2s.audit(self.paths)

    def failed(self,part):
        r=self.result();self.assertEqual(r['status'],'FAIL');self.assertIn(part,r['error'])

    def test_reconstructs_both_corners_and_all_four_real_paths(self):
        r=self.result();self.assertEqual(r['status'],'PASS',r)
        self.assertFalse(r['unconditional_board_qualification'])
        for corner in r['corners'].values():
            self.assertEqual(set(corner['outputs']),set(i2s.PORTS))
            self.assertAlmostEqual(corner['outputs']['i2s_bck']['ff_to_pad_rise_ns'],0.65)
            self.assertGreater(corner['receiver_margins']['i2s_din']['setup_remaining_ns'],0)

    def test_constraints_cannot_be_relaxed_or_false_pathed(self):
        p=self.paths['constraints'];original=p.read_text()
        for text in (original.replace('set_max_delay 4.000 -datapath_only -to [get_ports i2s_sck]','set_max_delay 5.000 -datapath_only -to [get_ports i2s_sck]'),
                     original+'\nset_false_path -to [get_ports i2s_din]\n',
                     original+'\ncreate_generated_clock -name i2s_bck -divide_by 40 [get_ports i2s_bck]\n'):
            p.write_text(text);self.failed('I2S')

    def test_rtl_dividers_and_edge_contract_cannot_change(self):
        p=self.paths['rtl'];original=p.read_text()
        for old,new in (('sck_half == 4','sck_half == 5'),('bck_half == 19','bck_half == 18'),
                        ('posedge clk','negedge clk'),('if (falling_bck)','if (pcm_valid)')):
            p.write_text(original.replace(old,new));self.failed('I2S')

    def test_missing_pad_or_ambiguous_driver(self):
        p=self.paths['slow_netlist']
        p.write_text(self.netlist.replace('.O(i2s_din)','.O(unused_output)'));self.failed('physical driver')
        p.write_text(self.netlist+'\nV_OBUFT \\extra (.O(i2s_din), .I(i2s_din_net), .T(1\'b0));');self.failed('physical driver')

    def test_actual_pad_bound_not_just_report_pass(self):
        p=self.paths['slow_sdf'];p.write_text(p.read_text().replace('(INSTANCE i2s_sck_pad) (DELAY (ABSOLUTE (PORT I (400) (400))','(INSTANCE i2s_sck_pad) (DELAY (ABSOLUTE (PORT I (5000) (5000))'))
        self.failed('real routed FF-to-pad bound')

    def test_actual_clock_branch_can_exhaust_setup_or_hold(self):
        p=self.paths['slow_sdf'];original=p.read_text()
        for port in ('i2s_din','i2s_bck'):
            p.write_text(original.replace(f'(INSTANCE {port}_ff) (DELAY (ABSOLUTE (PORT CK (100) (100))',f'(INSTANCE {port}_ff) (DELAY (ABSOLUTE (PORT CK (150000) (150000))'))
            self.failed('external setup/hold budget exhausted')

    def test_missing_tco_negative_arc_and_missing_corner_label(self):
        p=self.paths['slow_sdf'];original=p.read_text()
        for text,error in ((original.replace('(IOPATH CK Q (200) (200))',''),'Missing I2S SDF arc'),
                           (original.replace('(IOPATH CK Q (200) (200))','(IOPATH CK Q (-200) (200))'),'Negative/nonfinite'),
                           (original.replace('Slow Corner','Fast Corner'),'corner label')):
            p.write_text(text);self.failed(error)

    def test_different_routes_gated_buffer_or_clock_domain_rejected(self):
        p=self.paths['slow_netlist']
        p.write_text(self.netlist.replace('.D(next_value)','.D(other_value)',1));self.failed('different routed circuits')
        text=self.netlist.replace('"BUF_A"','"MUX_AB"')
        for corner in ('slow','fast'):self.paths[corner+'_netlist'].write_text(text)
        self.failed('ungated BUF_A')
        text=self.netlist.replace('.CK(audio_net)','.CK(other_clock)',1)
        for corner in ('slow','fast'):self.paths[corner+'_netlist'].write_text(text)
        self.failed('share the audio clock')

    def test_tristate_negative_edge_ff_and_unknown_sdf_arc_rejected(self):
        text=self.netlist.replace('.T(1\'b0)', '.T(control)',1)
        for corner in ('slow','fast'):self.paths[corner+'_netlist'].write_text(text)
        self.failed('tristated')
        text=self.netlist.replace('V_FFSYN','V_FFNEG',1)
        for corner in ('slow','fast'):self.paths[corner+'_netlist'].write_text(text)
        self.failed('physical driver')

    def test_complete_native_timing_required_and_original_files_hashed(self):
        r=self.result();self.assertEqual(set(r['evidence']),set(self.paths))
        for key,path in self.paths.items():self.assertEqual(r['evidence'][key]['sha256'],i2s.sha(path))
        self.paths['timing_report'].write_text('filtered fixture\nclock uncertainty -0.300\n')
        self.failed('complete passing routed timing')


if __name__=='__main__':unittest.main()
