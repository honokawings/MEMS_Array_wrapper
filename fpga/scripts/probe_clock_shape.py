from pathlib import Path
import subprocess, os
root=Path.cwd()
base=root/'fpga/build/io_probe/tap_018_drive_16_regional_sourcecontract'
out=root/'fpga/build/clock_shape_probe'
out.mkdir(parents=True,exist_ok=True)
top=(base/'io_probe.v').read_text()
top=top.replace('GTP_CLKBUFG u_eth_buf (.CLKIN(eth_in), .CLKOUT(eth_clk));', '''wire eth_250, eth_div, eth_locked;
 pango_audio_gpll #(.INPUT_MHZ(125.0), .INPUT_DIV(1), .OUTPUT_DIV(4))
   u_eth_pll(.clk_in(eth_in),.rst(~reset_n),.clk_out(eth_250),.locked(eth_locked));
 GTP_IOCLKDIV_E2 #(.DIV_FACTOR("2")) u_eth_div
   (.CLKIN(eth_250),.RST_N(reset_n & eth_locked),.CE(1'b1),.CLKDIVOUT(eth_div));
 GTP_CLKBUFG u_eth_buf (.CLKIN(eth_div), .CLKOUT(eth_clk));''')
(out/'io_probe.v').write_text(top)
pll=(root/'rtl/board/pango_board_clocks.v').read_text().replace('.STATIC_RATIOM(16)', '.STATIC_RATIOM(4)')
(out/'probe_clocks.v').write_text(pll)
(out/'pango_rgmii_io.v').write_bytes((base/'pango_rgmii_io.v').read_bytes())
(out/'pins.fdc').write_bytes((base/'pins.fdc').read_bytes())
timing=(base/'timing.fdc').read_text().replace('create_clock -name eth125 -period 8.000 [get_ports sys_clk_125_p]', '''create_clock -name ref125 -period 8.000 [get_ports sys_clk_125_p]
create_generated_clock -name eth250 -source [get_ports sys_clk_125_p] -multiply_by 2 [get_pins {u_eth_pll.u_gpll/CLKOUT0}]
create_generated_clock -name eth125 -source [get_pins {u_eth_pll.u_gpll/CLKOUT0}] -divide_by 2 [get_pins {u_eth_div/CLKDIVOUT}]
set_false_path -to [get_pins {u_eth_pll.u_gpll/RST u_eth_div/RST_N}]''').replace('pad_skew_ref','tx_pad_ref').replace('0.400','0.600')
(out/'timing.fdc').write_text(timing)
q=lambda p:'{'+p.as_posix()+'}'
commands=['set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676']
commands += ['add_design '+q(out/n) for n in ('io_probe.v','probe_clocks.v','pango_rgmii_io.v')]
commands += ['add_constraint '+q(out/n) for n in ('pins.fdc','timing.fdc')]
commands += ['compile -top_module io_probe','synthesize -ads -selected_syn_tool_opt 2','dev_map','pnr','report_timing -delay_type min_max -report_io_datasheet -report_max_skew -nworst 8 -max_path 40','gen_netlist -sdf_annotate FALSE -process_corner slow','puts "CLOCK_SHAPE_PROBE_COMPLETE"']
(out/'build.tcl').write_text('\n'.join(commands)+'\n')
env=os.environ.copy();env['PANGO_LICENSE_FILE']='D:/Application/ElectronicIDE/Pango/license/new_pds_F4A80DA47D72.lic'
with (out/'build.log').open('w') as log:
 r=subprocess.run(['D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4/bin/pds_shell.exe','-file',str(out/'build.tcl'),'-work_dir',str(out),'-project_name','ClockShape'],stdout=log,stderr=subprocess.STDOUT,env=env,cwd=out)
print(r.returncode)
print((out/'build.log').read_text(errors='replace')[-3000:])
