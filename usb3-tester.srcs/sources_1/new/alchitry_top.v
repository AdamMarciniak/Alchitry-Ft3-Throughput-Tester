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
    output wire        afe_rst_n
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
    // AFE5804: SPI init + LVDS auto-align sequencer (self-boots at power-up).
    // The UART debug console stays live on the Au's own USB2 port @ 2 Mbaud.
    //--------------------------------------------------------------------------
    wire [7:0]  afe_led;
    wire        afe_samp_clk;
    wire [11:0] afe_samp;
    wire        afe_samp_val;

    afe5804_ctrl #(
        .CLK_HZ (100_000_000),
        .BAUD   (2_000_000)
    ) u_afe (
        .clk          (clk_in),
        .rst_n        (rst_n),
        .usb_rx       (usb_rx),
        .usb_tx       (usb_tx),
        .led          (afe_led),
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

    afe_stream u_stream (
        .samp_clk (afe_samp_clk),
        .rst      (rst_sys),
        .samp     (afe_samp),
        .samp_val (afe_samp_val),
        .rd_clk   (clk_in),
        .rd_en    (adc_rd_en),
        .dout     (adc_word),
        .empty    (adc_empty)
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
        .streaming      (streaming),
        .cmd_count      (cmd_count)
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
    //--------------------------------------------------------------------------
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE ("block"),         // fast path: deep BRAM buffer
        .WRITE_DATA_WIDTH (32),
        .READ_DATA_WIDTH  (32),
        .FIFO_WRITE_DEPTH (2048),
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
    // Status LEDs
    //--------------------------------------------------------------------------
    assign led = {ft_locked,        // 7: FT601 MMCM locked
                  rx_locked,        // 6: magic word found, control channel live
                  streaming,        // 5: START received
                  afe_led[4],       // 4: AFE FCLK alive
                  afe_led[3],       // 3: AFE OUT1 activity
                  afe_led[2:0]};    // 2:0 AFE phase (101 = LOCKED, 110 = FAILED)
endmodule