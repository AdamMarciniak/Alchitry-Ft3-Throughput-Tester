#==============================================================================
# Bitstream configuration
#==============================================================================
set_property BITSTREAM.GENERAL.COMPRESS TRUE      [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 66       [current_design]
set_property CONFIG_VOLTAGE 3.3                   [current_design]
set_property CFGBVS VCCO                          [current_design]
set_property BITSTREAM.CONFIG.SPI_32BIT_ADDR NO   [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4      [current_design]
set_property BITSTREAM.CONFIG.SPI_FALL_EDGE YES   [current_design]

#==============================================================================
# Board peripherals
#==============================================================================
set_property PACKAGE_PIN N14 [get_ports {clk}]
set_property IOSTANDARD LVCMOS33 [get_ports {clk}]
create_clock -period 10.0 -name clk_0 -waveform {0.000 5.0} [get_ports clk]

set_property PACKAGE_PIN P6  [get_ports {rst_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {rst_n}]

set_property PACKAGE_PIN K13 [get_ports {led[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[0]}]
set_property PACKAGE_PIN K12 [get_ports {led[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[1]}]
set_property PACKAGE_PIN L14 [get_ports {led[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[2]}]
set_property PACKAGE_PIN L13 [get_ports {led[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[3]}]
set_property PACKAGE_PIN M15 [get_ports {led[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[4]}]
set_property PACKAGE_PIN M14 [get_ports {led[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[5]}]
set_property PACKAGE_PIN M12 [get_ports {led[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[6]}]
set_property PACKAGE_PIN P14 [get_ports {led[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[7]}]

set_property PACKAGE_PIN P15 [get_ports {usb_rx}]
set_property IOSTANDARD LVCMOS33 [get_ports {usb_rx}]
set_property PACKAGE_PIN P16 [get_ports {usb_tx}]
set_property IOSTANDARD LVCMOS33 [get_ports {usb_tx}]

#==============================================================================
# AFE5804 LVDS inputs  (Alchitry A45-A53, bank @ 3.3V VCCO)
# EXTERNAL 100 ohm termination at the connector -> NO DIFF_TERM
#==============================================================================
# A47 / A45  -- LCLK, 240 MHz bit clock.  A47 must be clock-capable (BUFR).
set_property PACKAGE_PIN F5  [get_ports {lclk_p}]
set_property IOSTANDARD LVDS_25 [get_ports {lclk_p}]
set_property PACKAGE_PIN E5  [get_ports {lclk_n}]
set_property IOSTANDARD LVDS_25 [get_ports {lclk_n}]

# A48 / A46  -- FCLK, 40 MHz frame clock
set_property PACKAGE_PIN F4  [get_ports {fclk_p}]
set_property IOSTANDARD LVDS_25 [get_ports {fclk_p}]
set_property PACKAGE_PIN F3  [get_ports {fclk_n}]
set_property IOSTANDARD LVDS_25 [get_ports {fclk_n}]

# A53 / A51  -- OUT1, 480 Mbps data
set_property PACKAGE_PIN B4  [get_ports {out1_p}]
set_property IOSTANDARD LVDS_25 [get_ports {out1_p}]
set_property PACKAGE_PIN A3  [get_ports {out1_n}]
set_property IOSTANDARD LVDS_25 [get_ports {out1_n}]

create_clock -period  4.167 -name lclk [get_ports lclk_p]   ;# 240 MHz
create_clock -period 25.000 -name fclk [get_ports fclk_p]   ;#  40 MHz

#==============================================================================
# AFE5804 SPI  (Alchitry B70-B78)
#==============================================================================
set_property PACKAGE_PIN M5  [get_ports {afe_sclk}]         ;# B78
set_property IOSTANDARD LVCMOS33 [get_ports {afe_sclk}]
set_property PACKAGE_PIN N4  [get_ports {afe_cs_n}]         ;# B76
set_property IOSTANDARD LVCMOS33 [get_ports {afe_cs_n}]
set_property PACKAGE_PIN T4  [get_ports {afe_sdata}]        ;# B72
set_property IOSTANDARD LVCMOS33 [get_ports {afe_sdata}]
set_property PACKAGE_PIN T3  [get_ports {afe_rst_n}]        ;# B70
set_property IOSTANDARD LVCMOS33 [get_ports {afe_rst_n}]

#==============================================================================
# Timing: three unrelated clock domains; monitors are async/static
#==============================================================================
set_clock_groups -asynchronous \
  -group [get_clocks -include_generated_clocks clk_0] \
  -group [get_clocks -include_generated_clocks fclk] \
  -group [get_clocks -include_generated_clocks lclk]

set_false_path -to   [get_ports {afe_cs_n afe_sclk afe_sdata afe_rst_n}]
set_false_path -from [get_ports {rst_n usb_rx}]
set_false_path -to   [get_ports {usb_tx led[*]}]
set_false_path -from [get_ports out1_p]