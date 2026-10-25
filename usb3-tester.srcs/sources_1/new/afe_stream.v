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
    output wire        empty,

    // Sample-grid phase reference for tx_sequencer.  The AFE runs on its own
    // oscillator, so this grid free-runs against clk_in; a burst launched from
    // the clk_in domain lands anywhere on it, and the capture window (which
    // can only start on a FIFO-word boundary) picks up a uniform 0-50 ns error
    // per element.  This toggles once every 8 samples - always at the same
    // point of the pair/word grid, since pairing is slaved to the same seq
    // counter - so the sequencer can pin its first HV edge to the grid and the
    // error collapses to one constant absorbed by t0.
    output wire        sync_tog
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

    reg sync_r = 1'b0;

    always @(posedge samp_clk) begin
        wpush <= 1'b0;
        if (rst_s) begin
            seq   <= 4'd0;
            have0 <= 1'b0;
        end else if (samp_val) begin
            seq <= seq + 1'b1;
            // seq[2:0] == 7 is the closing sample of a pair (pairs are formed
            // at even seq), so the toggle sits at a fixed offset from the word
            // boundary by construction - the only property that matters.
            if (seq[2:0] == 3'd7) sync_r <= ~sync_r;
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

    assign sync_tog = sync_r;

    //--------------------------------------------------------------------------
    // CDC FIFO: samp_clk (80 MHz write) -> rd_clk (100 MHz read).
    // 20 Mwords/s sustained; 4096 deep = 205 us of slack - longer than any
    // receive window in use, so a bus stall now has to outlast the WHOLE
    // window before samples are dropped.  At 1024 (51 us) the `holes` counter
    // was catching ~1% of windows losing samples mid-trace at 10 cm: the frame
    // still arrived well-formed, but everything after the hole sat at the
    // wrong depth, and the shift changed frame to frame - flickering,
    // depth-smeared clutter that no host arithmetic can undo.  BRAM is 12%
    // used; these three extra RAMB36 are the cheapest image quality on the die.
    //--------------------------------------------------------------------------
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE ("block"),
        .WRITE_DATA_WIDTH (32),
        .READ_DATA_WIDTH  (32),
        .FIFO_WRITE_DEPTH (4096),
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
