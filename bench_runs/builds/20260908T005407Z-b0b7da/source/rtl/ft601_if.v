`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ft601_interface
// Description: FT601Q Sync 245 master, TX-optimised.
//
//   WRITE: fully pipelined, one word per ft_clk, IOB-launched on clk_ft_out.
//          The word in flight when TXE_N deasserts is dropped by the chip
//          (1 word, hardware-measured) and automatically replayed on resume.
//   READ : AN_421-style burst - OE_N low, then RD_N held LOW CONTINUOUSLY
//          until the FT601 ends the burst by deasserting RXF_N.  The chip
//          only commits consumed data on a completed burst; deasserting RD_N
//          early aborts and re-presents the buffer (infinite re-read loop).
//          One word is captured per burst (the first), so the host must send
//          one 4-byte write per command, spaced in time.  A stale multi-word
//          backlog drains and commits in a single burst (first word kept,
//          rest discarded) - which is the desired flush behaviour.
//          The round-trip latency (RD_N out -> data captured) is discovered at
//          runtime: the window of candidate capture cycles is searched for
//          RX_MAGIC on the first read, and the offset is latched.
//
//   Host protocol: the FIRST word written to the FPGA after reset must be
//   RX_MAGIC.  Everything after that is normal control data.
//////////////////////////////////////////////////////////////////////////////////

module ft601_interface #(
    parameter integer RD_WINDOW = 4,              // candidate capture slots
    parameter [31:0]  RX_MAGIC  = 32'hA5A5_5A5A   // host's first word
)(
    input  wire        clk_ft,          // 0 deg   - FSM, capture, FIFO ports
    input  wire        clk_ft_out,      // 205 deg - output IOBs ONLY

    inout  wire [31:0] ft_data,
    inout  wire [3:0]  ft_be,
    input  wire        ft_txe_n,
    input  wire        ft_rxf_n,
    output wire        ft_oe_n,
    output wire        ft_rd_n,
    output wire        ft_wr_n,

    input  wire        rst,

    // TX (the fast path)
    input  wire [31:0] tx_fifo_data,
    input  wire        tx_fifo_empty,
    output wire        tx_fifo_rd_en,

    // RX (the slow control path)
    output reg  [31:0] rx_fifo_data,
    output reg         rx_fifo_wr_en,
    input  wire        rx_fifo_full,

    // Status
    output reg                       rx_locked,
    output reg [$clog2(RD_WINDOW)-1:0] rx_offset   // RX_LATENCY = rx_offset + 1
);

    //--------------------------------------------------------------------------
    // Input capture - ILOGIC, 0 deg
    //--------------------------------------------------------------------------
    (* IOB = "TRUE" *) reg        txe_n_r;
    (* IOB = "TRUE" *) reg        rxf_n_r;
    (* IOB = "TRUE" *) reg [31:0] ft_data_in_r;

    always @(posedge clk_ft) begin
        if (rst) begin
            txe_n_r <= 1'b1;
            rxf_n_r <= 1'b1;
        end else begin
            txe_n_r <= ft_txe_n;
            rxf_n_r <= ft_rxf_n;
        end
    end

    always @(posedge clk_ft) ft_data_in_r <= ft_data;

    //--------------------------------------------------------------------------
    // TX word staging + 1-deep replay.
    // Staging keeps BRAM Tco out of the half-cycle path to the IOBs.
    // Replay: WR_N/data launch one chip edge after the FSM decision, so when
    // TXE_N deasserts, the word issued on the previous FSM cycle arrives at a
    // full FT601 and is dropped (hardware-measured: exactly 1 word lost per
    // TXE_N deassert).  That word is recaptured into tx_word and resent when
    // TXE_N recovers; the staged-but-unsent word parks in tx_stash meanwhile.
    // The IOB feed stays a plain register (tx_word), so the timing-critical
    // clk_ft -> clk_ft_out half-cycle path is untouched.
    //--------------------------------------------------------------------------
    reg  [31:0] tx_word;
    reg         tx_word_valid;
    reg  [31:0] tx_last_word;    // most recently issued word
    reg         tx_issued_d;     // wr_issue delayed one cycle
    reg  [31:0] tx_stash;        // displaced staged word during a replay
    reg         tx_stash_valid;
    wire        wr_issue;

    wire        tx_drop = txe_n_r && tx_issued_d;   // last issue was killed
    wire        tx_load = !tx_fifo_empty && !tx_drop &&
                          (!tx_word_valid || (wr_issue && !tx_stash_valid));

    assign tx_fifo_rd_en = tx_load;

    always @(posedge clk_ft) begin
        if (rst) begin
            tx_word        <= 32'h0;
            tx_word_valid  <= 1'b0;
            tx_last_word   <= 32'h0;
            tx_issued_d    <= 1'b0;
            tx_stash       <= 32'h0;
            tx_stash_valid <= 1'b0;
        end else begin
            tx_issued_d <= wr_issue;
            if (wr_issue) tx_last_word <= tx_word;

            if (tx_drop) begin
                // Resend the killed word first; park the staged word.
                tx_stash       <= tx_word;
                tx_stash_valid <= tx_word_valid;
                tx_word        <= tx_last_word;
                tx_word_valid  <= 1'b1;
            end else if (wr_issue && tx_stash_valid) begin
                tx_word        <= tx_stash;   // un-park after the replay went out
                tx_stash_valid <= 1'b0;
            end else if (tx_load) begin
                tx_word        <= tx_fifo_data;
                tx_word_valid  <= 1'b1;
            end else if (wr_issue) begin
                tx_word_valid  <= 1'b0;
            end
        end
    end

    //--------------------------------------------------------------------------
    // FSM
    //--------------------------------------------------------------------------
    localparam [2:0] S_IDLE    = 3'd0,
                     S_WRITE   = 3'd1,
                     S_RD_OE   = 3'd2,   // OE_N low, bus turnaround
                     S_RD_STB  = 3'd3,   // RD_N low for exactly one cycle
                     S_RD_WAIT = 3'd4,   // hold OE_N low, capture the window
                     S_TURN    = 3'd5;   // guard cycles, nobody drives

    localparam integer WAIT_CYCLES = RD_WINDOW + 2;

    reg  [2:0] state, next_state;
    reg  [3:0] wait_cnt;
    reg        rd_armed;    // gates reads to one per RXF# assertion

    reg        oe_n_c, rd_n_c, wr_n_c;
    reg        data_oe_c, be_oe_c;
    reg        rd_issue_c, wr_issue_c;

    assign wr_issue = wr_issue_c;

    // One read per RXF# assertion.  The FT601 holds RXF# low for a few cycles
    // after the word is consumed (deassertion latency); without rd_armed the
    // FSM would loop and issue phantom re-reads of the same word.  Re-arm only
    // once RXF# has returned high (buffer confirmed empty).
    wire read_req    = rd_armed && !rxf_n_r && !rx_fifo_full;
    wire write_ready = !txe_n_r && tx_word_valid;

    always @* begin
        next_state = state;
        oe_n_c     = 1'b1;
        rd_n_c     = 1'b1;
        wr_n_c     = 1'b1;
        data_oe_c  = 1'b0;
        be_oe_c    = 1'b0;
        rd_issue_c = 1'b0;
        wr_issue_c = 1'b0;

        case (state)
            // Reads win: they are rare, and starving them would deadlock
            // the host's write pipe.
            S_IDLE: begin
                if (read_req) begin
                    oe_n_c     = 1'b0;
                    next_state = S_RD_OE;
                end else if (write_ready) begin
                    data_oe_c  = 1'b1;
                    be_oe_c    = 1'b1;
                    wr_n_c     = 1'b0;
                    wr_issue_c = 1'b1;
                    next_state = S_WRITE;
                end
            end

            S_WRITE: begin
                if (write_ready && !read_req) begin
                    data_oe_c  = 1'b1;
                    be_oe_c    = 1'b1;
                    wr_n_c     = 1'b0;
                    wr_issue_c = 1'b1;
                end else begin
                    next_state = S_IDLE;
                end
            end

            S_RD_OE: begin
                oe_n_c     = 1'b0;
                next_state = S_RD_STB;
            end

            S_RD_STB: begin
                oe_n_c     = 1'b0;
                rd_n_c     = 1'b0;      // one cycle only -> one word consumed
                rd_issue_c = 1'b1;
                next_state = S_RD_WAIT;
            end

            S_RD_WAIT: begin
                oe_n_c = 1'b0;
                rd_n_c = 1'b0;          // HOLD RD_N low - AN_421-style burst.
                // The FT601 only commits a read when the burst runs to
                // completion: RD_N must stay asserted until the chip ends the
                // burst by deasserting RXF_N.  Deasserting RD_N early aborts
                // the burst and the buffer is re-presented from the start
                // (infinite re-read loop; host writes NAK once its buffer
                // blocks are exhausted).  Any queued backlog drains in one
                // continuous burst; only the first word (win[rx_offset]) is
                // pushed, so command delivery relies on the host contract:
                // one 4-byte write per command, spaced apart in time.
                if (wait_cnt == WAIT_CYCLES[3:0] && rxf_n_r)
                    next_state = S_TURN;
            end

            S_TURN: begin
                next_state = S_IDLE;
            end

            default: next_state = S_IDLE;
        endcase
    end

    always @(posedge clk_ft) begin
        if (rst) begin
            state    <= S_IDLE;
            wait_cnt <= 4'd0;
            rd_armed <= 1'b0;
        end else begin
            state <= next_state;
            if (state == S_RD_WAIT) begin
                if (wait_cnt != WAIT_CYCLES[3:0]) wait_cnt <= wait_cnt + 1'b1;
                // saturate: re-check the drain condition every cycle while held
            end else begin
                wait_cnt <= 4'd0;
            end

            // Arm when the FT601 shows the buffer empty (RXF# high); disarm the
            // instant we launch a read, so we take exactly one word per pulse.
            if (rxf_n_r)         rd_armed <= 1'b1;
            else if (rd_issue_c) rd_armed <= 1'b0;
        end
    end

    //--------------------------------------------------------------------------
    // Output IOB registers - 205 deg.  All outputs shift together.
    //--------------------------------------------------------------------------
    (* IOB = "TRUE" *) reg [31:0] ft_data_out_r;
    (* IOB = "TRUE" *) reg [31:0] ft_data_oe_r;
    (* IOB = "TRUE" *) reg [3:0]  ft_be_out_r;
    (* IOB = "TRUE" *) reg [3:0]  ft_be_oe_r;
    (* IOB = "TRUE" *) reg        ft_oe_n_r;
    (* IOB = "TRUE" *) reg        ft_rd_n_r;
    (* IOB = "TRUE" *) reg        ft_wr_n_r;

    always @(posedge clk_ft_out) begin
        if (rst) begin
            ft_data_out_r <= 32'h0;
            ft_data_oe_r  <= 32'h0;
            ft_be_out_r   <= 4'h0;
            ft_be_oe_r    <= 4'h0;
            ft_oe_n_r     <= 1'b1;
            ft_rd_n_r     <= 1'b1;
            ft_wr_n_r     <= 1'b1;
        end else begin
            ft_data_out_r <= tx_word;
            ft_data_oe_r  <= {32{data_oe_c}};
            ft_be_out_r   <= 4'b1111;
            ft_be_oe_r    <= {4{be_oe_c}};
            ft_oe_n_r     <= oe_n_c;
            ft_rd_n_r     <= rd_n_c;
            ft_wr_n_r     <= wr_n_c;
        end
    end

    genvar i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : g_dq
            assign ft_data[i] = ft_data_oe_r[i] ? ft_data_out_r[i] : 1'bz;
        end
        for (i = 0; i < 4; i = i + 1) begin : g_be
            assign ft_be[i] = ft_be_oe_r[i] ? ft_be_out_r[i] : 1'bz;
        end
    endgenerate

    assign ft_oe_n = ft_oe_n_r;
    assign ft_rd_n = ft_rd_n_r;
    assign ft_wr_n = ft_wr_n_r;

    //--------------------------------------------------------------------------
    // Capture window + runtime latency lock
    //
    //   rd_pipe[k] high during cycle N+k+1  (rd_issue was in cycle N)
    //   ft_data_in_r during cycle N+k+1     = bus sampled at edge N+k+1
    //   => win[k] holds the word at latency (k+1)
    //--------------------------------------------------------------------------
    reg [RD_WINDOW:0]  rd_pipe;
    reg [31:0]         win [0:RD_WINDOW-1];

    always @(posedge clk_ft) begin
        if (rst) rd_pipe <= {(RD_WINDOW+1){1'b0}};
        else     rd_pipe <= {rd_pipe[RD_WINDOW-1:0], rd_issue_c};
    end

    generate
        for (i = 0; i < RD_WINDOW; i = i + 1) begin : g_win
            always @(posedge clk_ft)
                if (rd_pipe[i]) win[i] <= ft_data_in_r;
        end
    endgenerate

    wire win_done = rd_pipe[RD_WINDOW];   // whole window captured

    integer j;
    reg     match;

    always @(posedge clk_ft) begin
        rx_fifo_wr_en <= 1'b0;

        if (rst) begin
            rx_locked <= 1'b0;
            rx_offset <= {$clog2(RD_WINDOW){1'b0}};
        end else if (win_done) begin
            if (!rx_locked) begin
                // First read after reset: find RX_MAGIC, latch its slot.
                match = 1'b0;
                for (j = 0; j < RD_WINDOW; j = j + 1) begin
                    if (!match && (win[j] == RX_MAGIC)) begin
                        rx_offset <= j[$clog2(RD_WINDOW)-1:0];
                        rx_locked <= 1'b1;
                        match     =  1'b1;
                    end
                end
                // No match -> stay unlocked, swallow the word, try the next one.
            end else begin
                rx_fifo_data  <= win[rx_offset];
                rx_fifo_wr_en <= 1'b1;
            end
        end
    end

endmodule