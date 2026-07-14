# check_impl.tcl - run the 5 post-implementation checks, write results to a log.
#
# Usage (Vivado Tcl Console, with the IMPLEMENTED/routed design open):
#     cd C:/Users/Adam/usb3-tester
#     source check_impl.tcl
#
# Results are written to impl_checks.log in this directory.

set logf "C:/Users/Adam/usb3-tester/impl_checks.log"

proc logline {logf s} {
    set fh [open $logf a]
    puts $fh $s
    puts $s
    close $fh
}

# start a fresh log
set fh [open $logf w]
puts $fh "==== impl checks: [clock format [clock seconds]] ===="
close $fh

# --- 1. AVAL-139 gone: MMCM phase is a valid 4.5 deg step (expect 202.500) ---
logline $logf "\n### 1. MMCM phase + AVAL-139"
logline $logf "CLKOUT1_PHASE = [get_property CLKOUT1_PHASE [get_cells u_ft_mmcm]]"
report_drc -checks {AVAL-139} -file $logf -append

# --- 2. NSTD-1 / UCIO-1 clear: every port has IOSTANDARD + LOC ---
report_drc -checks {NSTD-1 UCIO-1} -file $logf -append
set bad [get_ports -quiet -filter {LOC == "" || IOSTANDARD == ""}]
logline $logf "\n### 2b. Ports still missing LOC/IOSTANDARD (expect empty):"
logline $logf "unconstrained = $bad"

# --- 3. Timing MET, setup (max) on the FT601 outputs (expect ~ +0.97 ns) ---
report_timing -to [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}] \
              -delay_type max -max_paths 10 -nworst 1 -sort_by slack \
              -file $logf -append

# --- 4. Timing MET, hold (min) on the FT601 outputs (expect ~ +0.86 ns) ---
report_timing -to [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}] \
              -delay_type min -max_paths 10 -nworst 1 -sort_by slack \
              -file $logf -append

# --- 4b. Whole-design summary: WNS (setup) and WHS (hold) must both be > 0 ---
report_timing_summary -file $logf -append

# --- 5. Full DRC: confirm only the benign warnings remain ---
report_drc -file $logf -append

puts "DONE -> $logf"
