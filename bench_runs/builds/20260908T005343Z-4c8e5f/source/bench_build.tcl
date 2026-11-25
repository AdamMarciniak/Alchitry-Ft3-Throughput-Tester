# Non-project build from a frozen source snapshot. Invoked by bench_build.py.
set src [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set part [lindex $argv 2]
create_project -in_memory -part $part
set_property XPM_LIBRARIES {XPM_CDC XPM_MEMORY XPM_FIFO} [current_project]
read_verilog [glob [file join $src rtl *.v]]
read_xdc [glob [file join $src constraints *.xdc]]
synth_design -top alchitry_top -part $part
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -check_timing_verbose -file [file join $out timing.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out routing.rpt]
report_utilization -file [file join $out utilization.rpt]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup] == 0 || [llength $hold] == 0} {error "No timing paths returned"}
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
set failures [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == {Critical Warning}}]
set fh [open [file join $out checks.json] w]
puts $fh "{\"setup_slack_ns\": $wns, \"hold_slack_ns\": $whs, \"drc_failures\": [llength $failures]}"
close $fh
if {$wns < 0 || $whs < 0 || [llength $failures] != 0} {error "Build failed timing/DRC gates"}
write_checkpoint -force [file join $out routed.dcp]
write_bitstream -force -bin_file [file join $out alchitry_top.bit]
puts "BENCH_BUILD_PASS"
exit
