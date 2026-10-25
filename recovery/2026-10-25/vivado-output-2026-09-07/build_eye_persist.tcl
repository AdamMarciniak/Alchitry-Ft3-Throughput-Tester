open_project usb3-tester.xpr

reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "SYNTH_STATUS=$synth_status"
if {![string match "*Complete*" $synth_status]} {
    error "Synthesis did not complete"
}

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "IMPL_STATUS=$impl_status"
if {![string match "*Complete*" $impl_status]} {
    error "Implementation/bitstream did not complete"
}

open_run impl_1
report_timing_summary -file usb3-tester.runs/impl_1/eye_persist_timing_summary.rpt
report_drc -file usb3-tester.runs/impl_1/eye_persist_drc.rpt
close_project
exit
