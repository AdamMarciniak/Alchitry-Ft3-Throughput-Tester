`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ctrl_decode
// Description: Host->FPGA control word decoder + test pattern source +
//              pulse/receive sequencer + transmit sequencer config registers.
//              Entirely in the clk_in domain (RX FIFO read side).
//
//   Opcodes 0x10-0x1C are the transmit sequencer (tx_sequencer.v): burst
//   shape, the chirp table, the inter-stage waits, the element list, and
//   arm/stop.  They are
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
//   and it holds 4096 words (~205 us).  Overrun that and samples are dropped
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
//   capture_ready now feeds the pulser: after its nominal quiet window it
//   waits for the actual drain and DAC gap before changing elements. This
//   prevents USB stalls from silently skipping physical firings. The receive
//   origin still never waits on USB. Runtime-info flags bit 2 advertises the
//   capture-ready interlock. Unsolicited tx_sync while busy is still ignored.
//////////////////////////////////////////////////////////////////////////////////

`ifndef USB3_BENCH_BUILD_ID
`define USB3_BENCH_BUILD_ID 32'h00000000
`endif
module ctrl_decode #(
    parameter integer LEASE_CYCLES_PER_MS = 100000
) (
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
    input  wire [1:0]  tx_kind,
    output reg  [1:0]  pls_method,
    input  wire [5:0]  tx_elem,         // element closed in the mux tree, valid
                                        //   from the LE latch through the burst
    output wire        capture_ready,  // same clock: next shot may be scheduled

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
    output reg  [7:0]  pls_chirp_len,   // half cycles from the table, 0 = fixed burst
    output reg         pls_ch_wr,       // 1-cycle pulse
    output reg  [7:0]  pls_ch_addr,
    output reg  [15:0] pls_ch_data,
    output reg         pls_tr_wr,       // 1-cycle pulse
    output reg  [5:0]  pls_tr_addr,     // ELEMENT index, not list slot
    output reg  [11:0] pls_tr_data,     // transmit trim, clk cycles

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
                     OP_SEQ_TGC   = 8'h0D,   // payload: TGC acc increment per window
                                             //   word (50 ns of real time - the ramp
                                             //   is clocked, not drain-driven)
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
                     OP_PLS_FCLR    = 8'h1A, // clear a latched pulser fault
                     OP_PLS_CHIRP   = 8'h1B, // payload: {addr[7:0], drive[15:0]}
                                             //   chirp-table write, one half cycle
                     OP_PLS_TRIM    = 8'h1D, // payload: {elem[5:0], cycles[11:0]}
                                             //   per-element transmit trim
                     OP_PLS_LEASE   = 8'h1E, // 1..5000 ms host lease; 0 disables only while disarmed
                     OP_INFO_NONCE  = 8'h1F, // nonce echoed by SRC_INFO, writable only while disarmed
                     OP_PLS_CLEN    = 8'h1C; // payload[7:0]: chirp half cycles,
                                             //   0 = fixed burst (n_cycles/t_drive)

    localparam [1:0] PAT_COUNTER = 2'd0,
                     PAT_LFSR    = 2'd1,
                     PAT_CONST   = 2'd2;

    localparam [1:0] SRC_PATTERN = 2'd0,
                     SRC_ADC     = 2'd1,
                     SRC_SEQ     = 2'd2,
                     SRC_INFO    = 2'd3; // disarmed runtime build/configuration query

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

    // Optional unattended-run lease. Once enabled, missing renewals park the
    // pulser even if USB or the host process has stopped. Renewal never arms it.
    reg lease_enabled;
    reg [12:0] lease_ms;
    reg [16:0] lease_tick;
    reg [23:0] info_nonce;
    wire lease_expiring = lease_enabled && (lease_ms == 1) &&
                          (lease_tick == LEASE_CYCLES_PER_MS-1);

    //--------------------------------------------------------------------------
    // Command execution
    //--------------------------------------------------------------------------
    always @(posedge clk) begin
        rst_cnt_pulse <= 1'b0;
        afe_wr        <= 1'b0;
        pls_el_wr     <= 1'b0;
        pls_ch_wr     <= 1'b0;
        pls_tr_wr     <= 1'b0;
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

            // Programming/reset must not start transmission during a bench run.
            pls_method    <= 0;
            pls_arm       <= 1'b0;
            lease_enabled <= 1'b0;
            lease_ms      <= 13'd0;
            lease_tick    <= 17'd0;
            info_nonce    <= 24'd0;
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
            pls_chirp_len <= 8'd0;        // fixed burst until a host asks for a chirp
            pls_ch_addr   <= 8'd0;
            pls_ch_data   <= 16'd0;
            pls_tr_addr   <= 6'd0;
            pls_tr_data   <= 12'd0;   // trim_tab itself resets to all-zero
        end else begin
            if (lease_enabled) begin
                if (lease_ms == 0) begin
                    pls_arm <= 1'b0;
                end else if (lease_tick == LEASE_CYCLES_PER_MS-1) begin
                    lease_tick <= 17'd0;
                    lease_ms <= lease_ms - 1'b1;
                    if (lease_ms == 1) pls_arm <= 1'b0;
                end else begin
                    lease_tick <= lease_tick + 1'b1;
                end
            end
          if (ctrl_rd_en) begin
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
                OP_PLS_ARM:     pls_arm <= payload[0] &&
                    (!lease_enabled || ((lease_ms != 0) && !lease_expiring));
                OP_PLS_LEASE: begin
                    if ((payload >= 1) && (payload <= 5000)) begin
                        lease_enabled <= 1'b1;
                        lease_ms <= payload[12:0];
                        lease_tick <= 17'd0;
                    end else if ((payload == 0) && !pls_arm) begin
                        lease_enabled <= 1'b0;
                        lease_ms <= 13'd0;
                        lease_tick <= 17'd0;
                    end
                end
                8'h20: if (!pls_arm && payload <= 2) pls_method <= payload[1:0];
                OP_INFO_NONCE: if (!pls_arm) info_nonce <= payload;
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
                OP_PLS_CHIRP: begin
                    pls_ch_addr <= payload[23:16];
                    pls_ch_data <= payload[15:0];
                    pls_ch_wr   <= 1'b1;
                end
                // Addressed by ELEMENT index, not list slot - see the trim
                // table note in tx_sequencer.v.
                OP_PLS_TRIM: begin
                    pls_tr_addr <= payload[17:12];
                    pls_tr_data <= payload[11:0];
                    pls_tr_wr   <= 1'b1;
                end
                OP_PLS_CLEN:    pls_chirp_len <= payload[7:0];

                default:      ;           // NOP, lock word, anything unknown
            endcase
          end
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
    reg [1:0]  kind;
    reg [5:0]  elem;                            // latched from tx_elem at tx_sync
    reg [15:0] frame_cnt;
    reg [23:0] dly_cnt;
    reg [15:0] rx_cnt;
    reg [23:0] tgc_acc;
    reg        hdr_pend;                        // header owed to the TX FIFO

    // GAIN TIMEBASE.  The VCA applies its gain at SAMPLE time, so the TGC ramp
    // must advance with the clock, not with rx_write: draining is whenever the
    // bus allows, and advancing the ramp on drain events made gain-vs-depth a
    // function of USB backpressure - stalled samples were taken at a stale
    // gain, then the ramp sprinted at up to 5x real time while the FIFO
    // caught up.  Same principle as the range gate above: anything that is
    // part of the time base must not be able to wait on the TX FIFO.
    // rt_cnt counts seq_len words of REAL window time (one word = 2 samples =
    // 5 clk at 40 MSPS); tgc_inc keeps its per-word meaning, so no host or
    // opcode change.  The +/-100 ppm drift of the free-running ADC oscillator
    // over a window is nanoseconds - noise against a ~us DAC update.
    reg [15:0] rt_cnt;                          // window words left, real time
    reg [2:0]  rt_div;                          // 5 clk = one 50 ns word

    wire seq_run = streaming && (src == SRC_SEQ);
    wire tx_ok   = !tx_full && !tx_wr_rst_busy;

    // Backpressure can extend S_RX beyond its nominal acoustic window. Do not
    // advance the physical element while that RF is still draining. Observe
    // an empty ADC FIFO once between shots to exclude an old backlog. Do not
    // require empty on the grid-tick edge: fresh ADC words recur periodically.
    // Other sources retain standalone pulser operation.
    reg drain_clean = 1'b0;
    always @(posedge clk) begin
        if (rst || !seq_run || ((sstate == S_ARMED) && tx_sync))
            drain_clean <= 1'b0;
        else if (((sstate == S_DAMP) || (sstate == S_ARMED)) && adc_empty)
            drain_clean <= 1'b1;
    end
    assign capture_ready = !seq_run ||
                           ((sstate == S_ARMED) && drain_clean && tx_ok);

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
            rt_cnt    <= 16'd0;
            rt_div    <= 3'd0;
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
                kind     <= tx_kind;
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
                    rt_cnt <= (seq_len == 16'd0) ? 16'd1 : seq_len;
                    rt_div <= 3'd4;
                    sstate <= S_RX;             // unconditional - that is the point
                end
            end
            // hdr_write can still fire here if the FIFO was busy through S_DLY;
            // rx_write is held off until it does, while adc_keep (asserted on
            // entry to S_RX) has the ADC FIFO buffering from the true window
            // start.  seq_dly = 0 is therefore fine: the header simply lands
            // after the window opened and costs FIFO slack, not range accuracy.
            S_RX: begin
                // Gain ramp on the real-time counter (see rt_cnt above), NOT
                // on rx_write.  Runs for exactly the window's duration, then
                // holds at its final value until the drain finishes.
                if (rt_cnt != 16'd0) begin
                    if (rt_div != 3'd0) rt_div <= rt_div - 3'd1;
                    else begin
                        rt_div  <= 3'd4;
                        rt_cnt  <= rt_cnt - 16'd1;
                        tgc_acc <= tgc_sum[24] ? 24'hFFFFFF : tgc_sum[23:0];
                    end
                end
                if (hdr_write) hdr_pend <= 1'b0;
                else if (rx_write) begin        // one ADC word drained
                    rx_cnt <= rx_cnt - 1'b1;
                    if (rx_cnt == 16'd1) begin
                        // Written after the ramp branch above, so on a shared
                        // cycle the snap back to minimum wins.
                        frame_cnt <= frame_cnt + 1'b1;
                        tgc_acc   <= {tgc_start, 12'd0};  // gain back to minimum
                        dly_cnt   <= seq_gap;
                        sstate    <= S_DAMP;
                    end
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

    wire pat_write = tx_ready && ((src == SRC_PATTERN) || ((src == SRC_INFO) && !pls_arm));
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
            SRC_INFO: case (counter[3:0])
                0: tx_din = 32'hB34D0001;
                1: tx_din = {8'd0, info_nonce};
                2: tx_din = `USB3_BENCH_BUILD_ID;
                3: tx_din = {16'h0001, 10'd0, pls_method, 1'b1, 1'b1, lease_enabled, pls_arm};
                4: tx_din = {19'd0, lease_ms};
                5: tx_din = {16'd0, seq_len};
                6: tx_din = {8'd0, seq_dly};
                7: tx_din = {8'd0, seq_gap};
                8: tx_din = {20'd0, tgc_start};
                9: tx_din = {8'd0, tgc_inc};
                10: tx_din = {8'd0, pls_n_cycles, pls_t_drive};
                11: tx_din = {16'd0, pls_t_dead};
                12: tx_din = {8'd0, pls_t_settle};
                13: tx_din = {8'd0, pls_t_inhibit};
                14: tx_din = {8'd0, pls_t_ring};
                15: tx_din = {8'd0, pls_t_rx};
            endcase
            // elem is 6 bits, so the zero guard above it is 2 bits wide and a
            // host header test is (word >> 22) == 0x384.
            // Driven off hdr_pend, not the state: the header can now be written
            // during S_DLY or after the window has opened, and hdr_write is the
            // only thing that consumes it either way.
            SRC_SEQ: tx_din = hdr_pend
                            ? {8'hE1, kind, elem, frame_cnt}
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
