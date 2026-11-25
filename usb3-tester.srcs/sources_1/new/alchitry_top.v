`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: alchitry_top
// Target:      xc7a35tftg256-2  (Alchitry Au V2 + Ft+ V2)
//////////////////////////////////////////////////////////////////////////////////

module alchitry_top #(
    // Phase of the output-launch clock, in degrees.
    // Required window at the pin: hold >= T4 (4.8 ns), setup <= 10 - T3 (1.0 ns).
    // MUST be a multiple of 45/CLKOUT1_DIVIDE = 45/10 = 4.5 deg (no fine phase
    // shift on MMCME2_BASE); otherwise STA models a phase the silicon cannot
    // produce (DRC AVAL-139).  202.5 = 45 * 4.5, the valid step nearest the
    // swept optimum of ~205.  Arrival moves ~0.028 ns per degree.
    parameter real FT_OUT_PHASE = 189.0
)(
    // FT601 physical bus
    input  wire        ft_clk,
    inout  wire [31:0] ft_data,
    inout  wire [3:0]  ft_be,        // NOW BIDIRECTIONAL
    input  wire        ft_txe_n,
    input  wire        ft_rxf_n,
    output wire        ft_oe_n,
    output wire        ft_rd_n,
    output wire        ft_wr_n,
    output wire        ft_reset,     // FT601 RESET_N, active low - drive high to run
    input  wire        ft_wakeup,    // FT601 WAKEUP_N - left as an input, pulled up

    // Core board
    input  wire        clk_in,       // 100 MHz onboard oscillator
    input  wire        rst_n,        // active-low button
    output wire [7:0]  led,
    input  wire        usb_rx,
    output wire        usb_tx,

    // AFE5804 analog frontend
    input  wire        lclk_p, lclk_n,   // 240 MHz LVDS bit clock
    input  wire        fclk_p, fclk_n,   // 40 MHz LVDS frame clock
    input  wire        out1_p, out1_n,   // 480 Mbps LVDS data (CH1)
    output wire        afe_sclk,
    output wire        afe_cs_n,
    output wire        afe_sdata,
    output wire        afe_rst_n,

    // DAC7554 (channel B -> ADC VCNTRL), write-only SPI
    output wire        dac_sync_n,
    output wire        dac_sclk,
    output wire        dac_din,

    // Pulser: MAX14866 mux daisy chain + MD1213 driver.  3.3 V LVCMOS.
    output wire        mux_clk,      // chain clock, idle 0, shifts on rising edge
    output wire        mux_din,      // chain data, idle 0, MSB first
    output wire        mux_le,       // ACTIVE LOW latch enable, idle 1
    output wire        mux_clr,      // ACTIVE HIGH clear, opens every switch
    input  wire        mux_dout,     // chain loopback from BR3 (unused for now)
    output wire        pulse_ina,    // MD1213 INA, ACTIVE HIGH, idle 0 -> +HV
    output wire        pulse_inb,    // MD1213 INB, ACTIVE LOW,  idle 1 -> -HV
    output wire        pulse_oe      // MD1213 OE, arm/kill, idle 0
);

    //--------------------------------------------------------------------------
    // ft_clk MMCM: 0 deg for logic, FT_OUT_PHASE for the output IOBs.
    // BUFG in the feedback path de-skews the clock network so the phase we ask
    // for is the phase we get at the pins.
    //--------------------------------------------------------------------------
    wire ft_clkfb, ft_clkfb_bufg;
    wire ft_clk0_raw, ft_clk180_raw;
    wire clk_ft, clk_ft_out;
    wire ft_locked;

    MMCME2_BASE #(
        .BANDWIDTH          ("OPTIMIZED"),
        .CLKIN1_PERIOD      (10.000),      // 100 MHz from the FT601
        .DIVCLK_DIVIDE      (1),
        .CLKFBOUT_MULT_F    (10.000),      // VCO = 1000 MHz
        .CLKOUT0_DIVIDE_F   (10.000),      // 100 MHz, 0 deg
        .CLKOUT0_PHASE      (0.000),
        .CLKOUT1_DIVIDE     (10),          // 100 MHz, launch phase
        .CLKOUT1_PHASE      (FT_OUT_PHASE),
        .STARTUP_WAIT       ("FALSE")
    ) u_ft_mmcm (
        .CLKIN1   (ft_clk),
        .CLKFBIN  (ft_clkfb_bufg),
        .CLKFBOUT (ft_clkfb),
        .CLKOUT0  (ft_clk0_raw),
        .CLKOUT1  (ft_clk180_raw),
        .LOCKED   (ft_locked),
        .PWRDWN   (1'b0),
        .RST      (1'b0),                  // do NOT drop the clock on button reset
        .CLKFBOUTB(), .CLKOUT0B(), .CLKOUT1B(), .CLKOUT2(), .CLKOUT2B(),
        .CLKOUT3(),  .CLKOUT3B(), .CLKOUT4(),  .CLKOUT5(), .CLKOUT6()
    );

    BUFG u_bufg_fb  (.I(ft_clkfb),      .O(ft_clkfb_bufg));
    BUFG u_bufg_ft0 (.I(ft_clk0_raw),   .O(clk_ft));
    BUFG u_bufg_ft1 (.I(ft_clk180_raw), .O(clk_ft_out));

    //--------------------------------------------------------------------------
    // Reset synchronizers (async assert, sync deassert) - one per domain
    //--------------------------------------------------------------------------
    wire arst    = !rst_n;
    wire ft_arst = arst || !ft_locked;

    (* ASYNC_REG = "TRUE" *) reg [1:0] sys_rst_sync = 2'b11;
    always @(posedge clk_in or posedge arst) begin
        if (arst) sys_rst_sync <= 2'b11;
        else      sys_rst_sync <= {sys_rst_sync[0], 1'b0};
    end
    wire rst_sys = sys_rst_sync[1];

    (* ASYNC_REG = "TRUE" *) reg [1:0] ft_rst_sync = 2'b11;
    always @(posedge clk_ft or posedge ft_arst) begin
        if (ft_arst) ft_rst_sync <= 2'b11;
        else         ft_rst_sync <= {ft_rst_sync[0], 1'b0};
    end
    wire rst_ft = ft_rst_sync[1];

    //--------------------------------------------------------------------------
    // FT601 RESET_N: hold low ~10 ms after config, then release so it enumerates
    //--------------------------------------------------------------------------
    reg [19:0] por_cnt = 20'h0;
    always @(posedge clk_in) begin
        if (!(&por_cnt)) por_cnt <= por_cnt + 1'b1;
    end
    assign ft_reset = &por_cnt;

    //--------------------------------------------------------------------------
    // AFE5804: SPI init + calibrated LVDS alignment (self-boots at power-up).
    // The UART debug console stays live on the Au's own USB2 port @ 2 Mbaud.
    //--------------------------------------------------------------------------
    wire [7:0]  afe_led;
    wire        afe_samp_clk;
    wire [11:0] afe_samp;
    wire        afe_samp_val;
    wire [23:0] afe_word;
    wire        afe_wr;

    afe5804_ctrl #(
        .CLK_HZ         (100_000_000),
        .BAUD           (2_000_000),
        // host/settings/afe_eye_latest.json, 2026-08-18 18:32 PDT:
        // 128 captures/tap, 256 validation captures, zero sync/ramp errors.
        // Disable the old shared-tap scanner so it cannot overwrite these
        // independent centres with one value.
        .AUTO_EYE       (0),
        .ALIGN_DAT_TAP  (5'd10),
        .ALIGN_FCLK_TAP (5'd9)
    ) u_afe (
        .clk          (clk_in),
        .rst_n        (rst_n),
        .usb_rx       (usb_rx),
        .usb_tx       (usb_tx),
        .led          (afe_led),
        .ext_word     (afe_word),
        .ext_wr       (afe_wr),
        .lclk_p       (lclk_p),  .lclk_n(lclk_n),
        .fclk_p       (fclk_p),  .fclk_n(fclk_n),
        .out1_p       (out1_p),  .out1_n(out1_n),
        .afe_sclk     (afe_sclk),
        .afe_cs_n     (afe_cs_n),
        .afe_sdata    (afe_sdata),
        .afe_rst_n    (afe_rst_n),
        .stream_clk   (afe_samp_clk),
        .stream_data  (afe_samp),
        .stream_valid (afe_samp_val)
    );

    //--------------------------------------------------------------------------
    // ADC sample stream: tag + pack in the LVDS domain, cross to clk_in
    //--------------------------------------------------------------------------
    wire [31:0] adc_word;
    wire        adc_empty;
    wire        adc_rd_en;
    wire        adc_sync_tog;     // sample-grid phase, to tx_sequencer

    afe_stream u_stream (
        .samp_clk (afe_samp_clk),
        .rst      (rst_sys),
        .samp     (afe_samp),
        .samp_val (afe_samp_val),
        .rd_clk   (clk_in),
        .rd_en    (adc_rd_en),
        .dout     (adc_word),
        .empty    (adc_empty),
        .sync_tog (adc_sync_tog)
    );

    wire [31:0] ctrl_word;        // RX FIFO -> decoder (host command stream)
    wire        ctrl_empty;
    wire        ctrl_rd_en;
    wire [31:0] tx_din;           // decoder -> TX FIFO (pattern or ADC data)
    wire        tx_fifo_wr_en;
    wire        tx_fifo_full;
    wire        tx_wr_rst_busy;
    wire        streaming;
    wire [7:0]  cmd_count;
    wire [23:0] dac_rate;
    wire        dac_run;
    wire        tgc_en;
    wire [11:0] tgc_code;

    // tx_sequencer -> ctrl_decode: the capture trigger.  Declared up here
    // because ctrl_decode is instantiated before the sequencer that drives it.
    wire        pulse_tx_sync;
    wire [1:0]  pls_method, pulse_kind;
    wire [5:0]  pulse_element;
    wire        capture_ready;
    wire        pulse_fault;
    wire [3:0]  pulse_fault_code;
    wire [15:0] pulse_frames;
    wire [3:0]  pulse_state;

    // ctrl_decode -> tx_sequencer configuration (same clk_in domain, no CDC)
    wire        pls_arm;
    wire        pls_fault_clr;
    wire [7:0]  pls_n_cycles;
    wire [15:0] pls_t_drive;
    wire [15:0] pls_t_dead;
    wire [23:0] pls_t_settle;
    wire [23:0] pls_t_inhibit;
    wire [23:0] pls_t_ring;
    wire [23:0] pls_t_rx;
    wire [6:0]  pls_list_len;
    wire        pls_el_wr;
    wire [5:0]  pls_el_addr;
    wire [5:0]  pls_el_data;
    wire [7:0]  pls_chirp_len;
    wire        pls_ch_wr;
    wire [7:0]  pls_ch_addr;
    wire [15:0] pls_ch_data;
    wire        pls_tr_wr;
    wire [5:0]  pls_tr_addr;
    wire [11:0] pls_tr_data;

    ctrl_decode u_ctrl (
        .clk            (clk_in),
        .rst            (rst_sys),
        .ctrl_word      (ctrl_word),
        .ctrl_empty     (ctrl_empty),
        .ctrl_rd_en     (ctrl_rd_en),
        .tx_din         (tx_din),
        .tx_wr_en       (tx_fifo_wr_en),
        .tx_full        (tx_fifo_full),
        .tx_wr_rst_busy (tx_wr_rst_busy),
        .adc_word       (adc_word),
        .adc_empty      (adc_empty),
        .adc_rd_en      (adc_rd_en),
        .dac_rate       (dac_rate),
        .dac_run        (dac_run),
        .tgc_en         (tgc_en),
        .tgc_code       (tgc_code),
        // SRC_SEQ is slaved to the real transmit sequencer: every receive
        // window starts a fixed seq_dly after an actual HV burst, and carries
        // the element the mux tree really had closed.
        .tx_sync        (pulse_tx_sync),
        .tx_kind(pulse_kind), .pls_method(pls_method),
        .tx_elem        (pulse_element),
        .capture_ready  (capture_ready),
        .pls_fault      (pulse_fault),
        .pls_fault_code (pulse_fault_code),
        .pls_frames     (pulse_frames),
        .pls_state      (pulse_state),

        .pls_arm        (pls_arm),
        .pls_fault_clr  (pls_fault_clr),
        .pls_n_cycles   (pls_n_cycles),
        .pls_t_drive    (pls_t_drive),
        .pls_t_dead     (pls_t_dead),
        .pls_t_settle   (pls_t_settle),
        .pls_t_inhibit  (pls_t_inhibit),
        .pls_t_ring     (pls_t_ring),
        .pls_t_rx       (pls_t_rx),
        .pls_list_len   (pls_list_len),
        .pls_el_wr      (pls_el_wr),
        .pls_el_addr    (pls_el_addr),
        .pls_el_data    (pls_el_data),
        .pls_chirp_len  (pls_chirp_len),
        .pls_ch_wr      (pls_ch_wr),
        .pls_ch_addr    (pls_ch_addr),
        .pls_ch_data    (pls_ch_data),
        .pls_tr_wr      (pls_tr_wr),
        .pls_tr_addr    (pls_tr_addr),
        .pls_tr_data    (pls_tr_data),

        .afe_word       (afe_word),
        .afe_wr         (afe_wr),
        .streaming      (streaming),
        .cmd_count      (cmd_count)
    );

    //--------------------------------------------------------------------------
    // DAC7554: sawtooth ramp on channel B -> ADC VCNTRL attenuation sweep
    //--------------------------------------------------------------------------
    dac7554_ramp u_dac (
        .clk         (clk_in),
        .rst         (rst_sys),
        .step_cycles (dac_rate),
        .run         (dac_run),
        .tgc_en      (tgc_en),
        .tgc_code    (tgc_code),
        .dac_sync_n  (dac_sync_n),
        .dac_sclk    (dac_sclk),
        .dac_din     (dac_din)
    );

    //--------------------------------------------------------------------------
    // Transmit sequencer: MAX14866 mux chain + MD1213/TC6320 bipolar pulser.
    //
    // Timing, the chirp table and arm/stop come from ctrl_decode opcodes
    // 0x10-0x1C over the FT601 control pipe.  Same clk_in domain as the
    // decoder, so no CDC.
    //
    // The sequencer owns the timebase.  It is not gated by `streaming` and
    // keeps firing whether or not the host is capturing, but the receive path
    // is now slaved TO it: tx_sync (first HV edge) starts the SRC_SEQ receive
    // window and pulse_element becomes the frame header's element id, so every
    // captured window has a known time origin and a known element.  Stop the
    // pulser and the ADC stream goes quiet - by design.
    //
    // ctrl_decode resets pls_arm to 0, so programming and host loss park the
    // driver until an explicit arm request arrives.
    //--------------------------------------------------------------------------
    wire        pulse_busy;
    wire        pulse_chain_ok;
    // Chain loopback diagnostics.  Only the strobe is consumed below (LEDs);
    // the count / element / returned word are left as named nets so an ILA can
    // be dropped straight onto them - they synthesise away until one is.
    wire [15:0] pulse_chain_errs;
    wire [5:0]  pulse_chain_err_elem;
    wire [63:0] pulse_chain_err_word;
    wire        pulse_chain_err_stb;
    tx_sequencer #(
        .F_SYS         (100_000_000),
        .SPI_HALF      (5),            // 10 MHz chain clock
        .T_SETTLE_MIN  (400),          // 4.00 us - datasheet floor, host cannot go below
        .T_INHIBIT_MIN (450),          // 4.50 us - datasheet floor, host cannot go below
        .CHAIN_CHECK   (0),            // mux_dout floating - do not fault on it
        .N_ELEM        (48),

        // Root mux leaf taps: the three leaf muxes hang off root NO5/NO7/NO11,
        // so branch b closes root SW5/SW7/SW11 - not SW0/SW1/SW2.
        .ROOT_SW_BR0   (5),
        .ROOT_SW_BR1   (7),
        .ROOT_SW_BR2   (11),

        // ---- aperture walk --------------------------------------------------
        // MUX_STATIC = 0: the sequencer sweeps aperture positions 0..47 left to
        // right, one element per transmit event, and tx_sequencer's mux_code()
        // table turns each position into the root/leaf switch pair the
        // connector actually wired it to.  Every element receives on the same
        // single RX path, so nothing downstream of the mux tree changes.
        //
        // Set MUX_STATIC back to 1 for the single-element bench mode: the FSM,
        // the timing and the frame length are identical, but every element
        // rewrites one fixed chain word so the switches never move.  The
        // parameters below are hardware coordinates (chain device + NO pin),
        // not aperture positions - SW5 / BR1.NO10 was the element used for the
        // first tissue echoes, chain word 64'h0000_0000_0400_0020.
        .MUX_STATIC      (0),
        .MUX_STATIC_ROOT (5),          // root SW5  -> COM5/NO5, feeds leaf 1
        .MUX_STATIC_BR   (0),          // leaf 1 = BR1 = chain device after root
        .MUX_STATIC_CH   (10)          // leaf SW10 -> COM10/NO10
    ) u_tx (
        .clk             (clk_in),
        .rst             (rst_sys),

        // Burst launch holds for this grid tick so the capture start lands at
        // a constant offset from the burst instead of a random 0-50 ns one.
        .adc_sync_tog    (adc_sync_tog),
        .capture_ready   (capture_ready),

        .arm             (pls_arm),
        .start_frame     (1'b0),
        .continuous      (1'b1),
        .fault_clr       (pls_fault_clr),

        .cfg_n_cycles    (pls_n_cycles),
        .cfg_t_drive     (pls_t_drive),
        .cfg_t_dead      (pls_t_dead),
        .cfg_method(pls_method), .shot_kind(pulse_kind),
        .cfg_chirp_len   (pls_chirp_len),
        .ch_wr           (pls_ch_wr),
        .ch_wr_addr      (pls_ch_addr),
        .ch_wr_data      (pls_ch_data),
        .cfg_t_settle    (pls_t_settle),
        .cfg_t_inhibit   (pls_t_inhibit),
        .cfg_t_ring      (pls_t_ring),
        .cfg_t_rx        (pls_t_rx),

        .el_wr           (pls_el_wr),
        .el_wr_addr      (pls_el_addr),
        .el_wr_data      (pls_el_data),
        .cfg_list_len    (pls_list_len),
        .tr_wr           (pls_tr_wr),
        .tr_wr_addr      (pls_tr_addr),
        .tr_wr_data      (pls_tr_data),

        .mux_clk         (mux_clk),
        .mux_din         (mux_din),
        .mux_le          (mux_le),
        .mux_clr         (mux_clr),
        .mux_dout        (mux_dout),
        .pulse_ina       (pulse_ina),
        .pulse_inb       (pulse_inb),
        .pulse_oe        (pulse_oe),
        .tx_sync         (pulse_tx_sync),

        .busy            (pulse_busy),
        .element_current (pulse_element),
        .chain_ok        (pulse_chain_ok),
        .chain_err_cnt   (pulse_chain_errs),
        .chain_err_elem  (pulse_chain_err_elem),
        .chain_err_word  (pulse_chain_err_word),
        .chain_err_stb   (pulse_chain_err_stb),
        .fault           (pulse_fault),
        .fault_code      (pulse_fault_code),
        .frame_count     (pulse_frames),
        .dbg_state       (pulse_state)
    );

    //--------------------------------------------------------------------------
    // FIFO interconnect
    //--------------------------------------------------------------------------
    wire [31:0] tx_fifo_data;     // TX FIFO -> FT601 core (fast path)
    wire        tx_fifo_empty;
    wire        tx_fifo_rd_en;

    wire [31:0] rx_ctrl_data;     // FT601 core -> RX FIFO (slow control path)
    wire        rx_ctrl_wr_en;
    wire        rx_ctrl_full;

    wire        rx_locked;
    wire [1:0]  rx_offset;

    //--------------------------------------------------------------------------
    // TX FIFO : clk_in (write, decoder) -> clk_ft (read, FT601 core).
    // Deep BRAM buffer so the 100 MHz pattern source can run ahead of the bus.
    // 8192 words (32 KB) - together with the deepened ADC FIFO this gives the
    // sequencer ~2.5 receive windows of total elasticity against FT601 TXE
    // stalls, where 2048+1024 gave 12.3 kB and ~1% of windows lost samples
    // mid-trace at 10 cm (see afe_stream.v).  BRAM cost: +6 RAMB36 of the 44
    // that were free.
    //--------------------------------------------------------------------------
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE ("block"),         // fast path: deep BRAM buffer
        .WRITE_DATA_WIDTH (32),
        .READ_DATA_WIDTH  (32),
        .FIFO_WRITE_DEPTH (8192),
        .READ_MODE        ("fwft"),
        .FIFO_READ_LATENCY(0),
        .USE_ADV_FEATURES ("1000"),
        .CDC_SYNC_STAGES  (2)
    ) u_tx_fifo (
        .rst        (rst_sys),
        .wr_clk     (clk_in),
        .wr_en      (tx_fifo_wr_en),
        .din        (tx_din),
        .full       (tx_fifo_full),
        .wr_rst_busy(tx_wr_rst_busy),

        .rd_clk     (clk_ft),
        .rd_en      (tx_fifo_rd_en),
        .dout       (tx_fifo_data),
        .empty      (tx_fifo_empty),

        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        .almost_full(), .almost_empty(), .prog_full(), .prog_empty(),
        .wr_data_count(), .rd_data_count(), .data_valid(), .underflow(),
        .overflow(), .rd_rst_busy(), .sbiterr(), .dbiterr()
    );

    //--------------------------------------------------------------------------
    // RX FIFO : clk_ft (write, FT601 core) -> clk_in (read, decoder).
    // Tiny distributed-RAM buffer; control channel is low-rate.
    //--------------------------------------------------------------------------
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE ("distributed"),   // control channel: tiny
        .WRITE_DATA_WIDTH (32),
        .READ_DATA_WIDTH  (32),
        .FIFO_WRITE_DEPTH (32),
        .READ_MODE        ("fwft"),
        .FIFO_READ_LATENCY(0),
        .USE_ADV_FEATURES ("1000"),
        .CDC_SYNC_STAGES  (2)
    ) u_rx_fifo (
        .rst        (rst_ft),
        .wr_clk     (clk_ft),
        .wr_en      (rx_ctrl_wr_en),
        .din        (rx_ctrl_data),
        .full       (rx_ctrl_full),

        .rd_clk     (clk_in),
        .rd_en      (ctrl_rd_en),        // decoder consumes commands
        .dout       (ctrl_word),
        .empty      (ctrl_empty),

        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        .almost_full(), .almost_empty(), .prog_full(), .prog_empty(),
        .wr_data_count(), .rd_data_count(), .data_valid(), .underflow(),
        .overflow(), .wr_rst_busy(), .rd_rst_busy(), .sbiterr(), .dbiterr()
    );

    //--------------------------------------------------------------------------
    // FT601 physical layer
    //--------------------------------------------------------------------------
    ft601_interface #(
        .RD_WINDOW (4),
        .RX_MAGIC  (32'hA5A5_5A5A)
    ) u_ft601_core (
        .clk_ft        (clk_ft),
        .clk_ft_out    (clk_ft_out),
        .ft_data       (ft_data),
        .ft_be         (ft_be),
        .ft_txe_n      (ft_txe_n),
        .ft_rxf_n      (ft_rxf_n),
        .ft_oe_n       (ft_oe_n),
        .ft_rd_n       (ft_rd_n),
        .ft_wr_n       (ft_wr_n),
        .rst           (rst_ft),

        .tx_fifo_data  (tx_fifo_data),
        .tx_fifo_empty (tx_fifo_empty),
        .tx_fifo_rd_en (tx_fifo_rd_en),

        .rx_fifo_data  (rx_ctrl_data),
        .rx_fifo_wr_en (rx_ctrl_wr_en),
        .rx_fifo_full  (rx_ctrl_full),

        .rx_locked     (rx_locked),
        .rx_offset     (rx_offset)
    );

    //--------------------------------------------------------------------------
    // Chain loopback indicators.
    //
    // Two views of the same event, because they answer different questions:
    //   sticky : has the mux chain EVER failed to write since reset.  A glance
    //            says whether the transmit path can be trusted at all.
    //   pulse  : ~1 us per mismatch.  This is the scope trigger - trigger on
    //            the rising edge with negative delay and the failing shift sits
    //            in the pre-trigger window on mux_clk / mux_din / mux_dout,
    //            where the rotation can be read straight off the screen.  The
    //            trigger RATE is also the error rate, which is the number that
    //            matters: an occasional miss and every-shot corruption look
    //            identical on the sticky bit.
    //
    // These ride on LEDs rather than a new header pin - the LED pins (K13..P14)
    // are real FPGA I/O and probe fine, and no pin assignment has to be guessed
    // against a header map.  To move one to the pulser header instead, add the
    // port here, a line to host/pulser.acf, and the PACKAGE_PIN it generates to
    // pulser.xdc, exactly as the eight pulser signals were done.
    //--------------------------------------------------------------------------
    localparam integer DBG_STRETCH = 100;      // 1.0 us at 100 MHz

    reg       chain_err_sticky  = 1'b0;
    reg [6:0] chain_err_stretch = 7'd0;

    always @(posedge clk_in) begin
        if (rst_sys) begin
            chain_err_sticky  <= 1'b0;
            chain_err_stretch <= 7'd0;
        end else if (pulse_chain_err_stb) begin
            chain_err_sticky  <= 1'b1;
            chain_err_stretch <= DBG_STRETCH - 1;
        end else if (chain_err_stretch != 7'd0) begin
            chain_err_stretch <= chain_err_stretch - 7'd1;
        end
    end

    wire chain_err_pulse = (chain_err_stretch != 7'd0);

    //--------------------------------------------------------------------------
    // Status LEDs
    //
    // led[4:3] were afe_led[4] (FCLK alive) and afe_led[3] (OUT1 activity).
    // Both are implied by led[2:0] == 101 (phase LOCKED), so they are the two
    // cheapest bits to spend on the chain check.  Swap the two lines back to
    // recover them.
    //--------------------------------------------------------------------------
    assign led = {ft_locked,         // 7: FT601 MMCM locked
                  rx_locked,         // 6: magic word found, control channel live
                  streaming,         // 5: START received
                  chain_err_pulse,   // 4: mux chain readback mismatch, 1 us pulse
                  chain_err_sticky,  // 3: ...any mismatch since reset
                  afe_led[2:0]};     // 2:0 AFE phase (101 = LOCKED, 110 = FAILED)
endmodule
