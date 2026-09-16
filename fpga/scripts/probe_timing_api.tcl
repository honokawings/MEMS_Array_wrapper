set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676
foreach command {gen_netlist generate_netlist report_clock report_clocks report_clock_timing report_clock_networks report_clock_utilization} {
 puts "PROBE $command"
 if {[catch {uplevel #0 [list $command -help]} reason]} {puts "NOT_AVAILABLE $reason"}
}
