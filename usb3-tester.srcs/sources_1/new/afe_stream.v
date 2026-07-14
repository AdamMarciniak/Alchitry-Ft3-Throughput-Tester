`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: afe_stream
// Description: AFE sample stream conditioner.
//
//   Runs in the LVDS rx_div domain (80 MHz).  Every 12-bit sample gets a
//   4-bit rolling sequence tag in the top nibble, then two samples are packed
//   into one 32-bit word (older sample in the low half, so a little-endian
//   uint16 view on the host is in time order):
//
//        word = { seq[n+1], samp[n+1],  seq[n], samp[n] }
//
//   Words cross to the clk_in domain through an async FIFO.  If the FIFO is
//   full (host stalled) whole pairs are dropped, never split; the sequence
//   tag keeps counting per SAMPLE, so any drop is visible on the host as a
//   seq discontinuity - same verification philosophy as the counter pattern.
//////////////////////////////////////////////////////////////////////////////////

module afe_stream (
    // write side - LVDS receiver domain
    input  wire        samp_clk,        // rx_div, 80 MHz
    input  wire        rst,             // async ok, synchronized locally
    input  wire [11:0] samp,
    input  wire        samp_val,        // 1-cycle pulse per sample (40 MSPS)

    // read side - clk_in domain (FWFT, like the RX control FIFO)
    input  wire        rd_clk,
    input  wire        rd_en,
    output wire [31:0] dout,
    output wire        empty
);

    //--------------------------------------------------------------------------
    // Reset sync into samp_clk (xpm_fifo_async rst must be wr_clk-synchronous)
    //--------------------------------------------------------------------------
    (* ASYNC_REG = "TRUE" *) reg [2:0] rs = 3'b111;
    always @(posedge samp_clk) rs <= {rs[1:0], rst};
    wire rst_s = rs[2];

    //--------------------------------------------------------------------------
    // Tag + pack
    //--------------------------------------------------------------------------
    reg  [3:0]  seq   = 4'd0;
    reg  [15:0] low   = 16'd0;
    reg         have0 = 1'b0;
    reg  [31:0] wdata = 32'd0;
    reg         wpush = 1'b0;
    wire        wfull;
    wire        wr_rst_busy;

    always @(posedge samp_clk) begin
        wpush <= 1'b0;
        if (rst_s) begin
            seq   <= 4'd0;
            have0 <= 1'b0;
        end else if (samp_val) begin
            seq <= seq + 1'b1;
            if (!have0) begin
                low   <= {seq, samp};
                have0 <= 1'b1;
            end else begin
                wdata <= {seq, samp, low};
                wpush <= !wfull && !wr_rst_busy;   // full -> drop whole pair
                have0 <= 1'b0;
            end
        end
    end

    //--------------------------------------------------------------------------
    // CDC FIFO: samp_clk (80 MHz write) -> rd_clk (100 MHz read).
    // 20 Mwords/s sustained; 1024 deep = 51 us of slack.
    //--------------------------------------------------------------------------
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE ("block"),
        .WRITE_DATA_WIDTH (32),
        .READ_DATA_WIDTH  (32),
        .FIFO_WRITE_DEPTH (1024),
        .READ_MODE        ("fwft"),
        .FIFO_READ_LATENCY(0),
        .USE_ADV_FEATURES ("1000"),
        .CDC_SYNC_STAGES  (2)
    ) u_adc_fifo (
        .rst        (rst_s),
        .wr_clk     (samp_clk),
        .wr_en      (wpush),
        .din        (wdata),
        .full       (wfull),
        .wr_rst_busy(wr_rst_busy),

        .rd_clk     (rd_clk),
        .rd_en      (rd_en),
        .dout       (dout),
        .empty      (empty),

        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0),
        .almost_full(), .almost_empty(), .prog_full(), .prog_empty(),
        .wr_data_count(), .rd_data_count(), .data_valid(), .underflow(),
        .overflow(), .rd_rst_busy(), .sbiterr(), .dbiterr()
    );

endmodule
