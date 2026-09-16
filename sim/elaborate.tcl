# Optional frontend check only. Vivado uses its built-in default part internally;
# this does not select the user's target FPGA, map cells, or generate a bitstream.
set root [file normalize [file join [file dirname [info script]] ..]]
create_project -in_memory mems_rtl_check
set_property include_dirs [list [file join $root rtl]] [current_fileset]
read_verilog -sv [glob [file join $root rtl *.sv]]
synth_design -rtl -top mems_array_top
puts "MEMS_RTL_ELABORATION_PASS"
close_project
