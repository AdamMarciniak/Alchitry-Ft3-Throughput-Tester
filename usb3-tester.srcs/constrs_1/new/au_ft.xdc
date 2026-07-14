#----- Bitstream / Configuration
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
set_property BITSTREAM.CONFIG.SPI_32BIT_ADDR NO [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.SPI_FALL_EDGE YES [current_design]
set_property BITSTREAM.CONFIG.UNUSEDPIN PULLNONE [current_design]

#----- Clocks
set_property -dict {PACKAGE_PIN N14 IOSTANDARD LVCMOS33} [get_ports clk_in]
create_clock -period 10.000 -name clk_100 [get_ports clk_in]

set_property -dict {PACKAGE_PIN D4 IOSTANDARD LVCMOS33} [get_ports ft_clk]
create_clock -period 10.000 -name ft_clk [get_ports ft_clk]
# The MMCM outputs are auto-derived generated clocks; reference them with
# -include_generated_clocks below.  Do NOT create_generated_clock by hand.

#----- Board peripherals (Alchitry Au V2 - from au_base.xdc)
set_property -dict {PACKAGE_PIN P6  IOSTANDARD LVCMOS33} [get_ports rst_n]

set_property -dict {PACKAGE_PIN K13 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN K12 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN L14 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN L13 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {led[4]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[5]}]
set_property -dict {PACKAGE_PIN M12 IOSTANDARD LVCMOS33} [get_ports {led[6]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {led[7]}]

set_property -dict {PACKAGE_PIN P15 IOSTANDARD LVCMOS33} [get_ports usb_rx]
set_property -dict {PACKAGE_PIN P16 IOSTANDARD LVCMOS33} [get_ports usb_tx]

#----- FT601 Control Interface Pins
set_property PACKAGE_PIN N6 [get_ports ft_wakeup]
set_property IOSTANDARD LVCMOS33 [get_ports ft_wakeup]
set_property PULLTYPE PULLUP [get_ports ft_wakeup]

set_property PACKAGE_PIN M6 [get_ports ft_reset]
set_property IOSTANDARD LVCMOS33 [get_ports ft_reset]
set_property PULLTYPE PULLUP [get_ports ft_reset]

set_property -dict {PACKAGE_PIN L2 IOSTANDARD LVCMOS33} [get_ports ft_rxf_n]
set_property -dict {PACKAGE_PIN L3 IOSTANDARD LVCMOS33} [get_ports ft_txe_n]

set_property PACKAGE_PIN P9 [get_ports ft_oe_n]
set_property IOSTANDARD LVCMOS33 [get_ports ft_oe_n]
set_property PULLTYPE PULLUP [get_ports ft_oe_n]

set_property PACKAGE_PIN N9 [get_ports ft_rd_n]
set_property IOSTANDARD LVCMOS33 [get_ports ft_rd_n]
set_property PULLTYPE PULLUP [get_ports ft_rd_n]

set_property PACKAGE_PIN J1 [get_ports ft_wr_n]
set_property IOSTANDARD LVCMOS33 [get_ports ft_wr_n]
set_property PULLTYPE PULLUP [get_ports ft_wr_n]

#----- FT601 Byte Enables
set_property -dict {PACKAGE_PIN H1 IOSTANDARD LVCMOS33} [get_ports {ft_be[0]}]
set_property -dict {PACKAGE_PIN K3 IOSTANDARD LVCMOS33} [get_ports {ft_be[1]}]
set_property -dict {PACKAGE_PIN K2 IOSTANDARD LVCMOS33} [get_ports {ft_be[2]}]
set_property -dict {PACKAGE_PIN K1 IOSTANDARD LVCMOS33} [get_ports {ft_be[3]}]

#----- FT601 Parallel 32-Bit Data Bus (Split: Bank 14: [15:0], Bank 35: [31:16])
set_property -dict {PACKAGE_PIN T8 IOSTANDARD LVCMOS33} [get_ports {ft_data[0]}]
set_property -dict {PACKAGE_PIN T7 IOSTANDARD LVCMOS33} [get_ports {ft_data[1]}]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports {ft_data[2]}]
set_property -dict {PACKAGE_PIN T9 IOSTANDARD LVCMOS33} [get_ports {ft_data[3]}]
set_property -dict {PACKAGE_PIN T5 IOSTANDARD LVCMOS33} [get_ports {ft_data[4]}]
set_property -dict {PACKAGE_PIN R5 IOSTANDARD LVCMOS33} [get_ports {ft_data[5]}]
set_property -dict {PACKAGE_PIN T12 IOSTANDARD LVCMOS33} [get_ports {ft_data[6]}]
set_property -dict {PACKAGE_PIN R12 IOSTANDARD LVCMOS33} [get_ports {ft_data[7]}]
set_property -dict {PACKAGE_PIN R7 IOSTANDARD LVCMOS33} [get_ports {ft_data[8]}]
set_property -dict {PACKAGE_PIN R6 IOSTANDARD LVCMOS33} [get_ports {ft_data[9]}]
set_property -dict {PACKAGE_PIN T13 IOSTANDARD LVCMOS33} [get_ports {ft_data[10]}]
set_property -dict {PACKAGE_PIN R13 IOSTANDARD LVCMOS33} [get_ports {ft_data[11]}]
set_property -dict {PACKAGE_PIN R8 IOSTANDARD LVCMOS33} [get_ports {ft_data[12]}]
set_property -dict {PACKAGE_PIN P8 IOSTANDARD LVCMOS33} [get_ports {ft_data[13]}]
set_property -dict {PACKAGE_PIN T15 IOSTANDARD LVCMOS33} [get_ports {ft_data[14]}]
set_property -dict {PACKAGE_PIN T14 IOSTANDARD LVCMOS33} [get_ports {ft_data[15]}]
set_property -dict {PACKAGE_PIN C4 IOSTANDARD LVCMOS33} [get_ports {ft_data[16]}]
set_property -dict {PACKAGE_PIN E3 IOSTANDARD LVCMOS33} [get_ports {ft_data[17]}]
set_property -dict {PACKAGE_PIN D3 IOSTANDARD LVCMOS33} [get_ports {ft_data[18]}]
set_property -dict {PACKAGE_PIN G2 IOSTANDARD LVCMOS33} [get_ports {ft_data[19]}]
set_property -dict {PACKAGE_PIN G1 IOSTANDARD LVCMOS33} [get_ports {ft_data[20]}]
set_property -dict {PACKAGE_PIN J5 IOSTANDARD LVCMOS33} [get_ports {ft_data[21]}]
set_property -dict {PACKAGE_PIN J4 IOSTANDARD LVCMOS33} [get_ports {ft_data[22]}]
set_property -dict {PACKAGE_PIN G5 IOSTANDARD LVCMOS33} [get_ports {ft_data[23]}]
set_property -dict {PACKAGE_PIN G4 IOSTANDARD LVCMOS33} [get_ports {ft_data[24]}]
set_property -dict {PACKAGE_PIN H5 IOSTANDARD LVCMOS33} [get_ports {ft_data[25]}]
set_property -dict {PACKAGE_PIN H4 IOSTANDARD LVCMOS33} [get_ports {ft_data[26]}]
set_property -dict {PACKAGE_PIN F2 IOSTANDARD LVCMOS33} [get_ports {ft_data[27]}]
set_property -dict {PACKAGE_PIN E1 IOSTANDARD LVCMOS33} [get_ports {ft_data[28]}]
set_property -dict {PACKAGE_PIN J3 IOSTANDARD LVCMOS33} [get_ports {ft_data[29]}]
set_property -dict {PACKAGE_PIN H3 IOSTANDARD LVCMOS33} [get_ports {ft_data[30]}]
set_property -dict {PACKAGE_PIN H2 IOSTANDARD LVCMOS33} [get_ports {ft_data[31]}]
#=============================================================================
# AFE5804 LVDS inputs  (Alchitry A45-A53)
# EXTERNAL 100 ohm termination at the connector -> NO DIFF_TERM
#=============================================================================
# A47 / A45  -- LCLK, 240 MHz bit clock.  F5 must be clock-capable (BUFR).
set_property -dict {PACKAGE_PIN F5 IOSTANDARD LVDS_25} [get_ports lclk_p]
set_property -dict {PACKAGE_PIN E5 IOSTANDARD LVDS_25} [get_ports lclk_n]

# A48 / A46  -- FCLK, 40 MHz frame clock
set_property -dict {PACKAGE_PIN F4 IOSTANDARD LVDS_25} [get_ports fclk_p]
set_property -dict {PACKAGE_PIN F3 IOSTANDARD LVDS_25} [get_ports fclk_n]

# A53 / A51  -- OUT1, 480 Mbps data
set_property -dict {PACKAGE_PIN B4 IOSTANDARD LVDS_25} [get_ports out1_p]
set_property -dict {PACKAGE_PIN A3 IOSTANDARD LVDS_25} [get_ports out1_n]

create_clock -period  4.167 -name lclk [get_ports lclk_p]   ;# 240 MHz
create_clock -period 25.000 -name fclk [get_ports fclk_p]   ;#  40 MHz

#=============================================================================
# AFE5804 SPI  (Alchitry B70-B78)
#=============================================================================
set_property -dict {PACKAGE_PIN M5 IOSTANDARD LVCMOS33} [get_ports afe_sclk]   ;# B78
set_property -dict {PACKAGE_PIN N4 IOSTANDARD LVCMOS33} [get_ports afe_cs_n]   ;# B76
set_property -dict {PACKAGE_PIN T4 IOSTANDARD LVCMOS33} [get_ports afe_sdata]  ;# B72
set_property -dict {PACKAGE_PIN T3 IOSTANDARD LVCMOS33} [get_ports afe_rst_n]  ;# B70

set_false_path -to   [get_ports {afe_cs_n afe_sclk afe_sdata afe_rst_n}]
set_false_path -from [get_ports out1_p]

#=============================================================================
# FT601Q Sync 245 timing - datasheet Table 4.2 (v1.05+)
#   T1 slave drive setup = 3.0 ns   T2 slave drive hold  = 3.5 ns
#   T3 master drive setup= 1.0 ns   T4 master drive hold = 4.8 ns
#=============================================================================

# FT601 -> FPGA:  max = period - T1 = 10.0 - 3.0 ;  min = T2
set_input_delay -clock ft_clk -max 7.000 [get_ports {ft_data[*] ft_be[*] ft_rxf_n ft_txe_n}]
set_input_delay -clock ft_clk -min 3.500 [get_ports {ft_data[*] ft_be[*] ft_rxf_n ft_txe_n}]

# FPGA -> FT601:  max = T3 ;  min = -T4
set_output_delay -clock ft_clk -max  1.000 [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}]
set_output_delay -clock ft_clk -min -4.800 [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}]

#----- Clock domain isolation.  clk_ft and clk_ft_out are BOTH derived from
#      ft_clk, so they stay in the same group - the half-cycle 0->180 paths
#      must be timed, not false-pathed.
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks clk_100] \
    -group [get_clocks -include_generated_clocks ft_clk] \
    -group [get_clocks -include_generated_clocks lclk] \
    -group [get_clocks -include_generated_clocks fclk]

set_false_path -from [get_ports rst_n]
set_false_path -from [get_ports usb_rx]
set_false_path -from [get_ports ft_wakeup]
set_false_path -to   [get_ports {usb_tx led[*] ft_reset}]

#----- I/O electrical.  Note: lowering DRIVE / using SLEW SLOW *increases* Tco
#      and is a secondary hold knob if the phase sweep leaves you short.
set_property SLEW FAST [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}]
set_property DRIVE 12  [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n}]
set_property IOB TRUE  [get_ports {ft_data[*] ft_be[*] ft_wr_n ft_rd_n ft_oe_n ft_rxf_n ft_txe_n}]

#----- Keep the shared bus from floating during turnaround
set_property PULLTYPE PULLUP [get_ports {ft_data[*] ft_be[*]}]