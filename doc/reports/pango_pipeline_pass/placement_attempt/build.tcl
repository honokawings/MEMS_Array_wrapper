set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/board/mems_array_pg2l200h.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/board/pango_board_clocks.v}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/board/pango_rgmii_io.v}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/cic_decimator.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/fir_decimator.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/mems_array_top.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/async_sample_fifo.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/ethernet_arp_rx.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/ethernet_udp_engine.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/mdio_clause22.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/mems_ethernet_core.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/pcm_udp_packetizer.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/reset_release.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/net/rtl8211f_manager.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/pcm_calibration.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/pcm_frame_fifo.sv}
add_design {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/pdm_capture.sv}
add_constraint {D:/Workspace/Modelsim/260902_MEMS_Array/fpga/constraints/board_pins.fdc}
add_constraint {D:/Workspace/Modelsim/260902_MEMS_Array/fpga/constraints/timing.fdc}
compile -top_module mems_array_pg2l200h -system_verilog -include_path {{D:/Workspace/Modelsim/260902_MEMS_Array/rtl} {D:/Workspace/Modelsim/260902_MEMS_Array/rtl/board}}
puts "MEMS_PANGO_COMPILE_COMPLETE"
synthesize -ads -selected_syn_tool_opt 2
puts "MEMS_PANGO_SYNTHESIZE_COMPLETE"
dev_map
puts "MEMS_PANGO_DEV_MAP_COMPLETE"
pnr
puts "MEMS_PANGO_PNR_COMPLETE"
report_timing
puts "MEMS_PANGO_REPORT_TIMING_COMPLETE"
