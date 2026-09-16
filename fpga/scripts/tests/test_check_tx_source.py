"""Synthetic parser/adversarial fixtures. Never hardware timing evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPT = Path(__file__).resolve().parents[1] / "check_tx_source.py"
spec = importlib.util.spec_from_file_location("check_tx_source", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def row(parent, values):
    node = ET.SubElement(parent, "row")
    for value in values:
        ET.SubElement(node, "data").text = str(value)
    return node


def path(parent, port, edge, maximum, reference=False):
    a = 5.2 if maximum else 5.0
    rel = a + (0.05 if maximum else -0.05)
    n = row(parent, ["Path", "", "", "", "ODDR/OCLK", port, "eth125", "tx_pad_ref",
                     "", "1.0", "", "", rel, 0.1 if maximum else -0.1])
    gc = ET.SubElement(ET.SubElement(n, "general_container"), "table_container")
    arrival = ET.SubElement(gc, "table", id="arrival", title=f"Data arrival time is {a:.3f}")
    row(arrival, ["N3", "", "0", "0", edge, "sys_clk_125_p (port)"])
    row(arrival, ["CLKBUF/O", "td", "4", "4", edge, "clock buffer"])
    row(arrival, ["ODDR/OCLK", "", "", "", edge, "ODDR/OCLK"])
    row(arrival, ["ODDR/DO", "tco", "0.2", "4.2", edge, "ODDR/DO"])
    row(arrival, ["G16", "", "", "", edge, port + " (port)"])
    required = ET.SubElement(gc, "table", id="require", title="Required time")
    row(required, ["clock uncertainty", "", -0.05 if maximum else 0.05, "", "", ""])
    row(required, ["Output external delay", "", 0, "", "", ""])
    row(required, ["clock pessimism", "", 0, "", "", ""])
    if not reference:
        path(n, "PHY0_TXC", edge, not maximum, reference=True)
    return n


def fixture():
    root = ET.Element("report")
    for corner in ("slow", "fast"):
        t = ET.SubElement(root, "table", id=f"report_timing_{corner}_path_max_skew")
        for edge in ("r", "f"):
            c = row(t, ["MaxSkew", 0.2, "", "", "", "", "", "", "", "", 0.4, 0.2, "", ""])
            for maximum in (True, False):
                g = row(c, ["skew for max path" if maximum else "skew for min path"])
                for port in sorted(gate.PORTS):
                    path(g, port, edge, maximum)
    return root


PORT_LIST = "[get_ports {PHY0_TXC PHY0_TXD[*] PHY0_TXCTRL}]"
FDC = "create_clock -name tx_pad_ref -period 8.000\n"
for edge in ("", " -clock_fall -add_delay"):
    for mm in ("max", "min"):
        FDC += f"set_output_delay -clock tx_pad_ref{edge} -{mm} 0.000 {PORT_LIST}\n"
for edge in ("rise", "fall"):
    FDC += f"set_max_skew -{edge}_from [get_clocks eth125] -to {PORT_LIST} 0.400\n"
FDC += f"set_max_delay 2.500 -datapath_only -from [get_clocks eth125] -to {PORT_LIST}\n"


class TxSourceGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.xml = fixture()
        self.fdc = FDC

    def audit(self, hardware_source=False):
        db, fdc = self.folder / "rtr.db", self.folder / "timing.fdc"
        ET.ElementTree(self.xml).write(db, encoding="utf-8")
        fdc.write_text(self.fdc)
        args = {} if hardware_source else dict(input_duty_min_percent=50, input_duty_max_percent=50, edge_jitter_budget_ns=0)
        return gate.audit_tx_source(db, fdc, **args)

    def paths(self):
        return self.xml.findall("table/row/row/row")

    def test_complete_synthetic_case(self):
        result = self.audit()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(result["cases"]), 4)
        self.assertEqual(sum(len(c["paths"]) for c in result["cases"]), 48)
        self.assertEqual(result["duty"]["status"], "PASS")

    def test_board_duty_not_inferred_from_ideal_clock(self):
        result = self.audit(hardware_source=True)
        self.assertEqual(result["skew_status"], "PASS")
        self.assertEqual(result["duty"]["status"], "FAIL")
        self.assertEqual(result["status"], "FAIL")

    def test_missing_corner_rejected(self):
        self.xml.remove(self.xml.findall("table")[1])
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_missing_clock_endpoint_rejected(self):
        g = self.xml.find("table/row/row")
        g.remove(g.findall("row")[0])
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_clock_tree_trimmed_by_exception_rejected(self):
        r = self.paths()[0].find("general_container/table_container/table[@id='arrival']/row")
        r.findall("data")[5].text = "ODDR/OCLK"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_noncommon_jitter_rejected(self):
        q = self.paths()[0].find("general_container/table_container/table[@id='require']/row")
        q.findall("data")[2].text = "-0.15"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_mixed_source_edge_rejected(self):
        q = self.paths()[0].find("row/general_container/table_container/table[@id='arrival']/row")
        q.findall("data")[4].text = "f"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_false_native_summary_rejected(self):
        self.xml.find("table/row").findall("data")[11].text = "0.1"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_long_output_datapath_rejected(self):
        self.paths()[0].findall("data")[9].text = "2.501"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_nonzero_source_phase_rejected(self):
        q = self.paths()[0].find("general_container/table_container/table[@id='arrival']/row")
        q.findall("data")[3].text = "4"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_txc_clock_model_rejected(self):
        self.fdc += "create_generated_clock -name fake [get_ports PHY0_TXC]\n"
        self.assertEqual(self.audit()["status"], "FAIL")

    def test_falsepath_rejected(self):
        self.fdc += "set_false_path -to [get_ports PHY0_TXC]\n"
        self.assertEqual(self.audit()["status"], "FAIL")

    def shaped_fixture(self, fall_ps=100):
        # These invented primitive delays test parsing/math only.
        netlist = '''
V_GPLL #(.STATIC_RATIOI(1), .STATIC_RATIOM(4), .STATIC_RATIOF(2), .STATIC_RATIO0(4), .INTERNAL_FB("CLKOUTF")) pll (.CLKOUT0(c250));
V_IOCLKDIV_E2 #(.DIV_FACTOR("2")) div (.CLKIN(c250), .CLKDIVOUT(c125), .CE(1'b1));
V_USCM #(.USCM_MODE("BUF_A")) buf (.CLK0(c125), .CLKOUT(clk));
V_OSERDES_E2 #(.OSERDES_MODE("DDR2TO1_SAME_EDGE")) oddr (.DI({1'bx,1'bx,1'bx,1'bx,1'bx,1'bx,1'b0,1'b1}), .OCLK(clk), .DO(tx), .OCE(1'b1));
V_OBUFT obuf (.I(tx), .O(PHY0_TXC), .T(1'b0));
'''
        cells = [
            ('V_IOCLKDIV_E2', 'div', '(PORT CLKIN (100) (500)) (IOPATH CLKIN CLKDIVOUT (100) (100))'),
            ('V_USCM', 'buf', '(PORT CLK0 (100) (100)) (IOPATH CLK0 CLKOUT (100) (100))'),
            ('V_OSERDES_E2', 'oddr', '(PORT OCLK (100) (100)) (IOPATH OCLK DO (100) (100))'),
            ('V_OBUFT', 'obuf', f'(PORT I (100) (100)) (IOPATH I O (100) ({fall_ps}))')]
        sdf = '(DELAYFILE (TIMESCALE 1 ps) ' + ''.join(
            f'(CELL (CELLTYPE "{t}") (INSTANCE {n}) (DELAY (ABSOLUTE {d})))' for t,n,d in cells) + ')'
        self.sdfs, self.nets = {}, {}
        for c in ('slow', 'fast'):
            self.sdfs[c] = self.folder / (c+'.sdf')
            self.nets[c] = self.folder / (c+'.v')
            self.sdfs[c].write_text('// '+c.capitalize()+' Corner\n'+sdf)
            self.nets[c].write_text(netlist)

    def test_real_edge_path_excludes_source_fall(self):
        self.shaped_fixture()
        result = gate.shaped_clock_duty(self.sdfs, self.nets)
        self.assertEqual(result['status'], 'PASS')
        # Divider input fall has 500 ps, rise 100 ps. Both output edges come
        # from input RISE, so the deliberately huge fall delay must cancel.
        for c in result['conservative_jitter_sensitivity']['cases']:
            self.assertEqual(c['fall_minus_rise_ns'], 0)
            self.assertEqual(c['maximum_duty_scenario']['duty_percent'], 54.5)
            self.assertEqual(c['minimum_duty_scenario']['duty_percent'], 45.5)
            self.assertEqual(c['maximum_duty_scenario']['period_ns'], 8)

    def test_duty_distortion_with_shared_edge_errors_rejected(self):
        self.shaped_fixture(fall_ps=229)
        result = gate.shaped_clock_duty(self.sdfs, self.nets)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['qualification_status'], 'UNCONFIRMED')
        self.assertEqual(result['conservative_jitter_sensitivity']['status'], 'FAIL')
        self.assertEqual(result['conservative_jitter_sensitivity']['cases'][0]['maximum_duty_scenario']['duty_percent'], 56.1125)
        self.assertEqual(result['required_edgepair_jitter_max_ns'], 0.271)

    def test_known_nominal_duty_violation_still_rejected(self):
        self.shaped_fixture(fall_ps=700)
        result = gate.shaped_clock_duty(self.sdfs, self.nets)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['nominal_model_status'], 'FAIL')

    def test_unknown_divider_does_not_claim_duty_correction(self):
        self.shaped_fixture()
        p = self.nets['slow']
        p.write_text(p.read_text().replace('DIV_FACTOR("2")','DIV_FACTOR("1")'))
        with self.assertRaises(gate.AuditError):
            gate.shaped_clock_duty(self.sdfs, self.nets)

    def test_txc_data_must_prove_clock_polarity(self):
        self.shaped_fixture()
        p = self.nets['slow']
        p.write_text(p.read_text().replace("1'b0,1'b1", "1'b1,1'b0"))
        with self.assertRaises(gate.AuditError):
            gate.shaped_clock_duty(self.sdfs, self.nets)

    def test_wrong_sdf_units_rejected(self):
        self.shaped_fixture()
        p = self.sdfs['slow']
        p.write_text(p.read_text().replace('TIMESCALE 1 ps','TIMESCALE 1 ns'))
        with self.assertRaises(gate.AuditError):
            gate.shaped_clock_duty(self.sdfs, self.nets)


if __name__ == "__main__":
    unittest.main()
