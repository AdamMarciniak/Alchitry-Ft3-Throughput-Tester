`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ctrl_decode
// Description: Host->FPGA control word decoder + test pattern source +
//              pulse/receive sequencer + transmit sequencer config registers.
//              Entirely in the clk_in domain (RX FIFO read side).
//
//   Opcodes 0x10-0x1A are the transmit sequencer (tx_sequencer.v): burst
//   shape, the inter-stage waits, the element list, and arm/stop.  They are
//   config registers only - the sequencer runs on its own timebase and is
//   NOT gated by streaming/START, so pulser commands never disturb the ADC
//   capture and the pulser keeps firing with no host attached.
//
//   SRC_SEQ captures one receive window per REAL transmit burst.  It is slaved
//   to tx_sequencer.v through tx_sync / tx_elem - there is no longer a pretend
//   pulser and no free-running local element counter:
//     1. S_ARMED: wait for tx_sync, the 1-cycle pulse tx_sequencer emits at the
//        first HV edge of a burst.  Latch tx_elem - the element the transmit
//        sequencer actually has closed in the mux tree - as this frame's id.
//     2. S_DLY: wait seq_dly clk cycles.  This is now a genuine range offset
//        measured from the first HV edge, not from an imaginary event.
//     3. S_RX: capture seq_len ADC words while tgc_code ramps tgc_start -> max
//        across the window; dac7554_ramp follows tgc_code so the VCA gain
//        sweeps up over the receive window (TGC)
//
//   THE RANGE GATE IS NOT ALLOWED TO WAIT ON THE TX FIFO.  There used to be an
//   S_HDR state between S_DLY and S_RX that held the window shut until the FIFO
//   accepted the header word, so any host/bus backpressure slid the gate by the
//   stall duration - a silent, unbounded range error, and one that `holes`
//   cannot see because outside S_RX the ADC FIFO is drained and discarded, so
//   nothing ever overflows to record it.  Measured on a link that had fallen
//   back to USB 2.0 it cost ~16 us per element.
//
//   The fix rests on the header needing to precede the DATA, not the window:
//   S_RX is now entered on the dly_cnt expiry alone, so adc_keep - and with it
//   the true time origin of the capture - is deterministic.  The header rides
//   in a `hdr_pend` flag and is written whenever the FIFO will take it, which
//   may be after the window opened; rx_write simply holds off until it lands.
//   Samples are not lost meanwhile because the ADC FIFO is accumulating from
//   the instant the window opened - it is the elastic buffer for exactly this,
//   and it holds 1024 words (~51 us).  Overrun that and samples are dropped
//   with a sequence-tag discontinuity, which is visible on the host, rather
//   than the gate moving, which is not.
//     4. S_DAMP: snap tgc_code back to tgc_start and hold off seq_gap clk
//        cycles so the VCNTRL step can ring out before re-arming.
//   Each window goes out the fast path as one frame:
//     word 0          : {8'hE1, 2'b00, elem[5:0], frame_cnt[15:0]}
//     word 1..seq_len : packed ADC pairs (afe_stream format)
//
//   HEADER FORMAT: the element field is 6 bits (bits 21:16) so it spans the
//   full 48-element aperture, and bits 23:22 are the zero guard, so the host
//   identifies a header as (word >> 22) == 0x384.  This is the contract
//   tfm_gl_host.py already implements via ELEM_BITS / HDR_SHIFT / HDR_MAGIC.
//
//   CONSEQUENCE OF SLAVING TO THE PULSER: no burst, no frame.  If the pulser
//   is stopped (pls_arm = 0) or sits in a latched fault, SRC_SEQ produces no
//   data at all - the ADC stream goes quiet rather than showing free-running
//   noise.  That is the point: every frame now has a known time origin.
//
//   If the pulser fires faster than a window can be captured and drained
//   (element period < seq_dly + window + seq_gap) the extra tx_sync pulses are
//   ignored and only every Nth burst is captured.  Frames are never torn; the
//   effective frame rate just drops.  Give the pulser an rx window at least as
//   long as the capture window to avoid it.
//////////////////////////////////////////////////////////////////////////////////

module ctrl_decode (
    input  wire        clk,             // clk_in (100 MHz onboard)
    input  wire        rst,             // rst_sys

    // From RX control FIFO (FWFT)
    input  wire [31:0] ctrl_word,
    input  wire        ctrl_empty,
    output wire        ctrl_rd_en,

    // To TX FIFO write port
    output reg  [31:0] tx_din,
    output wire        tx_wr_en,
    input  wire        tx_full,
    input  wire        tx_wr_rst_busy,

    // From ADC stream FIFO (FWFT, clk_in read side)
    input  wire [31:0] adc_word,
    input  wire        adc_empty,
    output wire        adc_rd_en,

    // DAC7554 ramp control (to dac7554_ramp)
    output reg  [23:0] dac_rate,        // clk cycles between ramp steps (0 = max)
    output reg         dac_run,         // 0 = freeze the ramp
    output wire        tgc_en,          // sequencer owns the DAC (TGC mode)
    output wire [11:0] tgc_code,        // TGC target code while tgc_en

    // Transmit sequencer feedback (tx_sequencer.v) - the capture trigger.
    input  wire        tx_sync,         // 1-cycle pulse at the first HV edge
    input  wire [5:0]  tx_elem,         // element closed in the mux tree, valid
                                        //   from the LE latch through the burst

    // Real transmit sequencer (tx_sequencer.v) config registers.  The
    // sequencer runs on its own timebase; the receive window above is slaved
    // to it through tx_sync, not the other way round.
    output reg         pls_arm,         // level: 0 parks the driver + clears muxes
    output reg         pls_fault_clr,   // 1-cycle pulse
    output reg  [7:0]  pls_n_cycles,
    output reg  [15:0] pls_t_drive,
    output reg  [15:0] pls_t_dead,
    output reg  [23:0] pls_t_settle,
    output reg  [23:0] pls_t_inhibit,
    output reg  [23:0] pls_t_ring,
    output reg  [23:0] pls_t_rx,
    output reg  [6:0]  pls_list_len,
    output reg         pls_el_wr,       // 1-cycle pulse
    output reg  [5:0]  pls_el_addr,
    output reg  [5:0]  pls_el_data,

    // AFE5804 register write (to afe5804_ctrl ext port)
    output reg  [23:0] afe_word,        // {addr[7:0], data[15:0]}
    output reg         afe_wr,          // 1-cycle pulse per write

    // Status
    output reg         streaming,
    output reg  [7:0]  cmd_count       // increments per accepted command
);

    localparam [7:0] OP_NOP       = 8'h00,
                     OP_START     = 8'h01,
                     OP_STOP      = 8'h02,
                     OP_RST_CNT   = 8'h03,
                     OP_SET_PAT   = 8'h04,
                     OP_SET_CONST = 8'h05,
                     OP_SET_LIMIT = 8'h06,
                     OP_SET_SRC   = 8'h07,   // payload[1:0]: 0 pattern, 1 ADC, 2 sequencer
                     OP_DAC_RATE  = 8'h08,   // payload: cycles between DAC steps
                     OP_DAC_RUN   = 8'h09,   // payload[0]: 1 = ramp, 0 = freeze
                     OP_AFE_REG   = 8'h0A,   // payload: {addr[7:0], data[15:0]}
                     OP_SEQ_LEN   = 8'h0B,   // payload[15:0]: ADC words per receive window
                     OP_SEQ_DLY   = 8'h0C,   // payload: pulse->receive delay, clk cycles
                     OP_SEQ_TGC   = 8'h0D,   // payload: TGC acc increment per captured word
                     OP_SEQ_GAP   = 8'h0E,   // payload: receive-end->pulse damp, clk cycles
                     OP_SEQ_TGC0  = 8'h0F,   // payload[11:0]: TGC start (min) DAC code

                     // ---- transmit sequencer (tx_sequencer.v) --------------
                     // All timing payloads are clk_in cycles (10 ns at 100 MHz).
                     OP_PLS_ARM     = 8'h10, // payload[0]: 1 = run, 0 = stop +
                                             //   park driver + CLR all muxes
                     OP_PLS_NCYC    = 8'h11, // payload[7:0]:  +/- pulse pairs per burst
                     OP_PLS_TDRIVE  = 8'h12, // payload[15:0]: width of each +HV/-HV pulse
                     OP_PLS_TDEAD   = 8'h13, // payload[15:0]: gap between opposite polarities
                     OP_PLS_TSETTLE = 8'h14, // payload: LE rise -> first HV edge
                     OP_PLS_TINHIB  = 8'h15, // payload: last HV edge -> chain clocking
                     OP_PLS_TRING   = 8'h16, // payload: ringdown blanking
                     OP_PLS_TRX     = 8'h17, // payload: echo receive window
                     OP_PLS_NELEM   = 8'h18, // payload[6:0]: elements per frame
                     OP_PLS_ELEM    = 8'h19, // payload: {addr[5:0], data[5:0]} list write
                     OP_PLS_FCLR    = 8'h1A; // clear a latched pulser fault

    localparam [1:0] PAT_COUNTER = 2'd0,
                     PAT_LFSR    = 2'd1,
                     PAT_CONST   = 2'd2;

    localparam [1:0] SRC_PATTERN = 2'd0,
                     SRC_ADC     = 2'd1,
                     SRC_SEQ     = 2'd2;

    // FWFT: one word per cycle whenever present
    assign ctrl_rd_en = !ctrl_empty;

    wire [7:0]  opcode  = ctrl_word[31:24];
    wire [23:0] payload = ctrl_word[23:0];

    reg [1:0]  pattern;
    reg [1:0]  src;
    reg [23:0] const_val;
    reg [31:0] word_limit;
    reg [31:0] words_sent;
    reg        rst_cnt_pulse;
    reg [15:0] seq_len;
    reg [23:0] seq_dly;
    reg [23:0] seq_gap;
    reg [23:0] tgc_inc;
    reg [11:0] tgc_start;

    //--------------------------------------------------------------------------
    // Command execution
    //--------------------------------------------------------------------------
    always @(posedge clk) begin
        rst_cnt_pulse <= 1'b0;
        afe_wr        <= 1'b0;
        pls_el_wr     <= 1'b0;
        pls_fault_clr <= 1'b0;

        if (rst) begin
            streaming  <= 1'b0;
            pattern    <= PAT_COUNTER;
            src        <= SRC_PATTERN;    // default: pattern (old tester behaviour)
            const_val  <= 24'hDEAD00;
            word_limit <= 32'h0;          // 0 = unlimited
            dac_rate   <= 24'd0;          // default: ramp at max SPI rate
            dac_run    <= 1'b1;           // ramp free-runs from power-up
            seq_len    <= 16'd2047;       // 4094 samples = 102.35 us window
            seq_dly    <= 24'd500;        // 5 us pulse->receive settling
            seq_gap    <= 24'd5000;       // 50 us DAC ring-out before next pulse
            tgc_inc    <= 24'd8196;       // full 0->4095 sweep over 2047 words
            tgc_start  <= 12'd0;          // ramp starts at DAC code 0
            cmd_count  <= 8'h0;

            // Pulser defaults: the settings validated on the scope.  arm=1 so
            // the transmit chain free-runs from power-up with no host present,
            // exactly as before this control path existed.
            pls_arm       <= 1'b1;
            pls_n_cycles  <= 8'd2;        // 2 positive + 2 negative pulses
            pls_t_drive   <= 16'd10;      // 100 ns per pulse
            pls_t_dead    <= 16'd4;       //  40 ns between polarities
            pls_t_settle  <= 24'd500;     // 5.00 us switch settle
            pls_t_inhibit <= 24'd450;     // 4.50 us SPI lockout
            pls_t_ring    <= 24'd300;     //   3 us ringdown blanking
            pls_t_rx      <= 24'd13_000;  // 130 us receive window
            pls_list_len  <= 7'd48;       // walk all 48 elements
            pls_el_addr   <= 6'd0;
            pls_el_data   <= 6'd0;
        end else if (ctrl_rd_en) begin
            cmd_count <= cmd_count + 1'b1;

            case (opcode)
                OP_START:     streaming <= 1'b1;
                OP_STOP:      streaming <= 1'b0;
                OP_RST_CNT: begin
                    streaming     <= 1'b0;
                    rst_cnt_pulse <= 1'b1;
                end
                OP_SET_PAT:   pattern    <= payload[1:0];
                OP_SET_CONST: const_val  <= payload;
                OP_SET_LIMIT: word_limit <= {payload, 8'h0};
                OP_SET_SRC:   src        <= payload[1:0];
                OP_DAC_RATE:  dac_rate   <= payload;
                OP_DAC_RUN:   dac_run    <= payload[0];
                OP_AFE_REG: begin
                    afe_word <= payload;
                    afe_wr   <= 1'b1;
                end
                OP_SEQ_LEN:   seq_len    <= payload[15:0];
                OP_SEQ_DLY:   seq_dly    <= payload;
                OP_SEQ_TGC:   tgc_inc    <= payload;
                OP_SEQ_GAP:   seq_gap    <= payload;
                OP_SEQ_TGC0:  tgc_start  <= payload[11:0];

                // ---- transmit sequencer ------------------------------------
                OP_PLS_ARM:     pls_arm       <= payload[0];
                OP_PLS_NCYC:    pls_n_cycles  <= payload[7:0];
                OP_PLS_TDRIVE:  pls_t_drive   <= payload[15:0];
                OP_PLS_TDEAD:   pls_t_dead    <= payload[15:0];
                OP_PLS_TSETTLE: pls_t_settle  <= payload;
                OP_PLS_TINHIB:  pls_t_inhibit <= payload;
                OP_PLS_TRING:   pls_t_ring    <= payload;
                OP_PLS_TRX:     pls_t_rx      <= payload;
                OP_PLS_NELEM:   pls_list_len  <= payload[6:0];
                OP_PLS_ELEM: begin
                    pls_el_addr <= payload[11:6];
                    pls_el_data <= payload[5:0];
                    pls_el_wr   <= 1'b1;
                end
                OP_PLS_FCLR:    pls_fault_clr <= 1'b1;

                default:      ;           // NOP, lock word, anything unknown
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // Pulse/receive sequencer (SRC_SEQ)
    //--------------------------------------------------------------------------
    localparam [2:0] S_DAMP  = 3'd0,            // DAC back at min, ring settling
                     S_ARMED = 3'd1,            // waiting for a real HV burst
                     S_DLY   = 3'd2,
                     // 3'd3 was S_HDR - deleted, see the note above.  Left
                     // unused rather than renumbered so the encodings the rest
                     // of this file compares against do not move.
                     S_RX    = 3'd4;

    reg [2:0]  sstate;
    reg [5:0]  elem;                            // latched from tx_elem at tx_sync
    reg [15:0] frame_cnt;
    reg [23:0] dly_cnt;
    reg [15:0] rx_cnt;
    reg [23:0] tgc_acc;
    reg        hdr_pend;                        // header owed to the TX FIFO

    wire seq_run = streaming && (src == SRC_SEQ);
    wire tx_ok   = !tx_full && !tx_wr_rst_busy;

    // The header may go out during the delay OR after the window has opened -
    // whichever the FIFO allows first.  Data waits for it so the frame is never
    // torn, but the WINDOW does not.
    wire hdr_write = seq_run && hdr_pend && tx_ok &&
                     ((sstate == S_DLY) || (sstate == S_RX));
    wire rx_write  = seq_run && (sstate == S_RX) && !hdr_pend &&
                     tx_ok && !adc_empty;

    assign tgc_en       = seq_run;
    assign tgc_code     = tgc_acc[23:12];

    wire [24:0] tgc_sum = {1'b0, tgc_acc} + {1'b0, tgc_inc};

    always @(posedge clk) begin
        if (rst || !seq_run) begin
            sstate    <= S_DAMP;
            dly_cnt   <= 24'd0;
            elem      <= 6'd0;
            frame_cnt <= 16'd0;
            hdr_pend  <= 1'b0;
            tgc_acc   <= {tgc_start, 12'd0};
        end else case (sstate)
            S_DAMP: begin                       // let the DAC min-step ring out
                dly_cnt <= dly_cnt - 1'b1;
                if (dly_cnt == 24'd0) sstate <= S_ARMED;
            end
            // Armed and waiting.  tx_sync fires on the first HV edge of the
            // burst; tx_elem has been stable since the LE latch several
            // microseconds earlier, so it is safe to sample on this edge.
            // Bursts that arrive in any other state are ignored - a frame is
            // never torn to chase one.
            S_ARMED: if (tx_sync) begin
                elem     <= tx_elem;            // whose element this frame is
                dly_cnt  <= seq_dly;
                hdr_pend <= 1'b1;               // owed from here until written
                sstate   <= S_DLY;
            end
            // Range offset from the HV edge.  Nothing in here may depend on the
            // TX FIFO: the expiry of this counter IS the time origin of the
            // capture, and if it can be stretched the whole delay model is a
            // fiction.  The header goes out opportunistically alongside.
            S_DLY: begin
                dly_cnt <= dly_cnt - 1'b1;
                if (hdr_write) hdr_pend <= 1'b0;
                if (dly_cnt == 24'd0) begin
                    rx_cnt <= (seq_len == 16'd0) ? 16'd1 : seq_len;
                    sstate <= S_RX;             // unconditional - that is the point
                end
            end
            // hdr_write can still fire here if the FIFO was busy through S_DLY;
            // rx_write is held off until it does, while adc_keep (asserted on
            // entry to S_RX) has the ADC FIFO buffering from the true window
            // start.  seq_dly = 0 is therefore fine: the header simply lands
            // after the window opened and costs FIFO slack, not range accuracy.
            S_RX: if (hdr_write) hdr_pend <= 1'b0;
            else if (rx_write) begin            // one ADC word captured
                rx_cnt <= rx_cnt - 1'b1;
                if (rx_cnt == 16'd1) begin
                    frame_cnt <= frame_cnt + 1'b1;
                    tgc_acc   <= {tgc_start, 12'd0};  // gain back to minimum
                    dly_cnt   <= seq_gap;
                    sstate    <= S_DAMP;
                end else begin
                    tgc_acc <= tgc_sum[24] ? 24'hFFFFFF : tgc_sum[23:0];
                end
            end
            default: sstate <= S_DAMP;          // unreachable encodings
        endcase
    end

    //--------------------------------------------------------------------------
    // Pattern source + TX FIFO write arbitration
    //--------------------------------------------------------------------------
    reg [31:0] counter;
    reg [31:0] lfsr;

    wire limit_hit = (word_limit != 32'h0) && (words_sent >= word_limit);
    wire tx_ready  = streaming && !limit_hit && tx_ok;

    wire pat_write = tx_ready && (src == SRC_PATTERN);
    wire adc_write = tx_ready && (src == SRC_ADC) && !adc_empty;

    // Sequencer frames bypass word_limit: a frame must never be cut short.
    assign tx_wr_en = pat_write || adc_write || hdr_write || rx_write;

    // Consume the ADC FIFO when a mode is capturing it; otherwise drain and
    // discard so a stream (or a receive window) always starts with fresh
    // samples, never a stale backlog.
    wire adc_keep = (streaming && (src == SRC_ADC)) ||
                    (seq_run && (sstate == S_RX));
    assign adc_rd_en = adc_write || rx_write || (!adc_keep && !adc_empty);

    always @(posedge clk) begin
        if (rst || rst_cnt_pulse) begin
            counter    <= 32'h0;
            lfsr       <= 32'hACE1_2345;   // any non-zero seed
            words_sent <= 32'h0;
        end else begin
            if (pat_write) begin
                counter <= counter + 1'b1;
                // maximal-length 32-bit XNOR LFSR, taps 32,22,2,1
                lfsr    <= {lfsr[30:0], ~(lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0])};
            end
            if (tx_wr_en) words_sent <= words_sent + 1'b1;
        end
    end

    always @* begin
        case (src)
            // elem is 6 bits, so the zero guard above it is 2 bits wide and a
            // host header test is (word >> 22) == 0x384.
            // Driven off hdr_pend, not the state: the header can now be written
            // during S_DLY or after the window has opened, and hdr_write is the
            // only thing that consumes it either way.
            SRC_SEQ: tx_din = hdr_pend
                            ? {8'hE1, 2'b00, elem, frame_cnt}
                            : adc_word;
            SRC_ADC: tx_din = adc_word;
            default: case (pattern)
                PAT_LFSR:  tx_din = lfsr;
                PAT_CONST: tx_din = {8'hC0, const_val};
                default:   tx_din = counter;   // PAT_COUNTER
            endcase
        endcase
    end

endmodule
