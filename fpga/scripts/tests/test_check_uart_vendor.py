"""Synthetic UART gate fixtures exercise rejection logic, not hardware evidence."""
from pathlib import Path
import importlib.util,json,sys,tempfile,unittest

SCRIPT=Path(__file__).resolve().parents[1]/'check_uart_vendor.py'
sys.path.insert(0,str(SCRIPT.parent))
spec=importlib.util.spec_from_file_location('uart_vendor_checker_test',SCRIPT)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
REPO=SCRIPT.parents[2]

def board_netlist():
    text=''
    for i in range(7):
        text+=f'''V_FFSYN /* g_uart.diagnostics/control/desired_channel[{i}]/FF0/FF */ #(.INIT(1'b0)) \\FF{i} (
 .Q(\\g_uart.diagnostics/desired_channel[{i}] ),.D(d{i}),.CK(ref),.CE(1'b1),.SR(rst));
 V_LUT1 #(.INIT(2'b10)) use{i}(.I0(\\g_uart.diagnostics/desired_channel[{i}] ),.Z(used{i}));\n'''
    return text+'''V_USCM #(.USCM_MODE("BUF_A")) globalclk(.CLKOUT(ref),.CLK0(buf));
 V_BUF pass(.Z(buf),.I(pad)); V_IBUF inputclk(.O(pad),.I(sys_clk_27));\n'''

class UartVendorAuditTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.build=self.root/'fpga/build/probe';self.log=self.root/'log/vendor_uart'
        for source in gate.SOURCES:self.put(source,(REPO/source).read_bytes())
        self.net=self.build/'synthesize/uart_audio_control_syn.vm'
        text=''
        for i in range(7):
            text+=f'''GTP_DFF_RE #(.INIT(1'b0)) ff{i}(.Q(q{i}),.D(d{i}),.CLK(clk),.R(rst),.CE(en));
 GTP_OUTBUF out{i}(.O(desired_channel[{i}]),.I(q{i}));\n'''
        self.put(self.net,text)
        self.put(self.build/'device_map/uart_audio_control_map.adf','Synthetic map fixture')
        self.put(self.build/'probe_timing.fdc','create_clock -name probe_sys -period 37.037 [get_ports {clk}]\n')
        flow=(f'set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676\n'
            f'add_design {{{(self.root/gate.SOURCES[0]).as_posix()}}}\nadd_constraint {{{(self.build/"probe_timing.fdc").as_posix()}}}\n'
            'compile -top_module uart_audio_control -system_verilog\nsynthesize -ads -selected_syn_tool_opt 2 -fanout_guide 256\ndev_map\n')
        self.put(self.build/'build.tcl',flow)
        self.tools=[self.root/'tools/pango/bin/pds_shell.exe']+[self.root/'tools/modelsim'/name for name in ('vlib.exe','vlog.exe','vsim.exe')]
        for path in self.tools:self.put(path,'Synthetic tool-hash fixture; never executed')
        model_dir=self.root/'tools/pango/arch/vendor/pango/verilog/simulation'
        self.models=[model_dir/'GTP_DFF_RE.v',model_dir/'GTP_OUTBUF.v']
        for path in self.models:self.put(path,'// Synthetic vendor-model hash fixture; never compiled\n')
        self.put(self.log/'pds_build.log',''.join(f'Executing : {stage} successfully.\n' for stage in ('compile','synthesize','dev_map')))
        self.put(self.log/'vlib.log','Synthetic success fixture\n')
        self.put(self.log/'vlog.log','vlog '+ ' '.join(str(p) for p in self.models+[self.net,self.root/gate.SOURCES[1]])+'\n')
        self.put(self.log/'vsim.log','[TB_DATA] gate_channels=128 channel_bit_zero_mask=7f channel_bit_one_mask=7f checks=55197 lines=143\n[TB_INFO] Simulation Finished!\n')
        runner_spec=importlib.util.spec_from_file_location('uart_gate_fixture_runner',REPO/gate.SOURCES[2])
        self.runner=importlib.util.module_from_spec(runner_spec);runner_spec.loader.exec_module(self.runner)
        cells=self.runner.parse_cells(self.net)
        self.result={'status':'PASS','scope':'vendor_uart_technology_netlist_functional','sdf_annotated':False,'placement_routing_tested':False,
            'device':{'family':'Logos2','device':'PG2L200H','speedgrade':'-6','package':'FBB676'},
            'sources_sha256':{p:gate.sha(self.root/p) for p in gate.SOURCES},
            'flow_evidence':[{'stage':s,'actual_success_marker':True} for s in ('compile','synthesize','dev_map')],
            'channels':128,'checks':55197,'response_lines':143,'primitive_kinds':['GTP_DFF_RE','GTP_OUTBUF'],
            'desired_channel_ff':self.runner.channel_ff_audit(cells),
            'tools_sha256':{str(p):gate.sha(p) for p in self.tools},'vendor_models_sha256':{str(p):gate.sha(p) for p in self.models},
            'artifacts_sha256':{p.relative_to(self.root).as_posix():gate.sha(p) for p in (self.build/'build.tcl',self.build/'probe_timing.fdc',self.build/'device_map/uart_audio_control_map.adf',self.net)},
            'raw_logs_sha256':{(self.log/p).relative_to(self.root).as_posix():gate.sha(self.log/p) for p in gate.LOGS}}
        self.result_path=self.log/'result.json';self.save()
        self.slow=self.build/'slow_sim.v';self.fast=self.build/'fast_sim.v'
        self.put(self.slow,board_netlist());self.put(self.fast,board_netlist())

    def put(self,path,value):
        path=Path(path)
        if not path.is_absolute():path=self.root/path
        path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(value,bytes):path.write_bytes(value)
        else:path.write_text(value,encoding='utf-8')
    def save(self):self.put(self.result_path,json.dumps(self.result))
    def reject_probe(self):
        self.save()
        with self.assertRaises((gate.AuditError,RuntimeError)):gate.verify_probe(self.root,self.result_path)
    def edit_log(self,name,text):
        path=self.log/name;self.put(path,text)
        self.result['raw_logs_sha256'][path.relative_to(self.root).as_posix()]=gate.sha(path)

    def test_complete_synthetic_fixture_contract(self):
        result=gate.audit(self.root,{'probe_result':self.result_path,'slow_netlist':self.slow,'fast_netlist':self.fast})
        self.assertEqual(result['status'],'PASS',result)
        self.assertEqual(result['corners']['slow']['variable_ff_count'],7)
    def test_probe_cannot_assert_routed_timing(self):self.result['placement_routing_tested']=True;self.reject_probe()
    def test_probe_cannot_assert_pass_without_all_channels(self):self.result['channels']=127;self.reject_probe()
    def test_probe_requires_full_negative_off_gain_response_count(self):self.result['response_lines']=128;self.reject_probe()
    def test_probe_source_change_is_rejected(self):self.put(gate.SOURCES[0],'module replaced; endmodule');self.reject_probe()
    def test_probe_tool_change_is_rejected(self):self.put(self.tools[0],'Changed binary fixture');self.reject_probe()
    def test_probe_missing_model_is_rejected(self):del self.result['vendor_models_sha256'][str(self.models[0])];self.reject_probe()
    def test_probe_missing_actual_pds_completion_is_rejected(self):
        self.edit_log('pds_build.log','Executing : compile successfully.\nExecuting : synthesize successfully.\n');self.reject_probe()
    def test_probe_rehashed_failure_log_is_rejected(self):
        self.edit_log('vsim.log',(self.log/'vsim.log').read_text()+'[TB_ERROR] failure\n');self.reject_probe()
    def test_probe_rehashed_rtl_compilation_is_rejected(self):
        self.edit_log('vlog.log',(self.log/'vlog.log').read_text()+str(self.root/gate.SOURCES[0])+'\n');self.reject_probe()
    def test_probe_rehashed_alternate_netlist_is_rejected(self):
        self.edit_log('vlog.log',(self.log/'vlog.log').read_text()+'alternate.v\n');self.reject_probe()
    def test_probe_asserted_ff_trace_must_match_netlist(self):self.result['desired_channel_ff'][6]['ports']['D']="1'b0";self.reject_probe()
    def test_routed_constant_fold_is_rejected(self):
        self.put(self.slow,'module constant; endmodule')
        with self.assertRaises(ValueError):gate.board_trace(self.slow)
    def test_routed_ff_constant_disabled_or_wrong_polarity_is_rejected(self):
        original=board_netlist()
        for old,new in (('.D(d6)',".D(1'b0)"),('.CE(1\'b1)',".CE(1'b0)"),('V_FFSYN','V_FFNEG'),('.Q(\\g_uart.diagnostics/desired_channel[6] )',".Q(1'b0)")):
            self.put(self.slow,original.replace(old,new))
            with self.subTest(new=new),self.assertRaises(gate.AuditError):gate.board_trace(self.slow)
    def test_routed_bit_missing_or_merged_is_rejected(self):
        self.put(self.slow,board_netlist().replace('desired_channel[6]/FF0','desired_channel[5]/FF0'))
        with self.assertRaises(gate.AuditError):gate.board_trace(self.slow)
    def test_routed_clock_must_be_physical_sys27_ungated_positive(self):
        for old,new in (('BUF_A','MUX'),('.I(sys_clk_27)','.I(sys_clk_125_p)'),('.CK(ref)','.CK(wrong)')):
            self.put(self.slow,board_netlist().replace(old,new))
            with self.subTest(new=new),self.assertRaises(gate.AuditError):gate.board_trace(self.slow)
    def test_routed_vbuf_clock_must_use_actual_vendor_Z_output(self):
        self.put(self.slow,board_netlist().replace('V_BUF pass(.Z(buf)','V_BUF pass(.O(buf)'))
        with self.assertRaises(gate.AuditError):gate.board_trace(self.slow)
    def test_routed_vbuf_clock_disconnected_input_is_rejected(self):
        self.put(self.slow,board_netlist().replace('V_BUF pass(.Z(buf),.I(pad))','V_BUF pass(.Z(buf),.I(disconnected))'))
        with self.assertRaises(gate.AuditError):gate.board_trace(self.slow)
    def test_routed_both_corners_must_have_identical_actual_connections(self):
        self.put(self.fast,board_netlist().replace('\\FF6 ','\\DifferentFF6 '))
        result=gate.audit(self.root,{'probe_result':self.result_path,'slow_netlist':self.slow,'fast_netlist':self.fast})
        self.assertEqual(result['status'],'FAIL');self.assertIn('identities or connections differ',result['error'])

if __name__=='__main__':unittest.main()
