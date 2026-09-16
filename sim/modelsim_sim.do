# Interactive ModelSim entry; paths are resolved relative to this script.
cd [file dirname [info script]]
if {![file isdirectory work]} { vlib work }
vlog -sv -lint -work work -f modelsim_filelist.f -l ../log/vlog_gui.log
vsim -voptargs=+acc work.tb_array
add wave -radix hexadecimal sim:/tb_array/dut/*
run -all
