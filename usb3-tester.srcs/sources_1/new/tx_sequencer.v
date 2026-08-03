`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: tx_sequencer
// Description: Sonic transmit sequencer - MAX14866 tree-mux daisy chain +
//              MD1213 driver / TC6320 bipolar HV pulser.
//
//   One transmit event per element:
//     S_SHIFT  -> 64 chain bits, LE high.  Overlaps the previous RX window.
//     S_WAITRX -> remainder of the previous receive window
//     S_TCS    -> t_CS guard, last CLK rising edge to LE falling
//     S_LATCH  -> LE low, the switches move here
//     S_SETTLE -> t_ON / t_OFF, analog node quiet at ground
//     S_FIRE_* -> n_cycles of  +HV / idle / -HV / idle  (return to zero)
//     S_INHIBIT-> MAX14866 SPI lockout after HV
//     then straight back to S_SHIFT for the next element, early in the RX
//     window where the echo data is ringdown-dominated anyway.
//
//   Electrical rules enforced here (README-sonic-tx-sequencer.md sec 5):
//     - pulse_ina is ACTIVE HIGH, pulse_inb is ACTIVE LOW.  Safe idle is
//       ina=0, inb=1.  ina=1 & inb=0 is shoot-through; an unconditional
//       combinational interlock at the bottom of this file blocks it, and a
//       fault is latched if it is ever seen.
//     - every polarity change routes through the idle state for >= t_dead and
//       only ONE of ina / inb changes at any transition.
//     - the burst always ends in the idle state.
//     - pulse_oe is an arm/kill signal, raised once per arm, never per pulse.
//     - mux_le is high for all 64 clock edges of a shift.
//     - mux_clk is a plain register in this clock domain: exactly 64 rising
//       edges per shift, no combinational clock, never tri-stated, and no
//       other logic can drive it.
//
//   Timing is in clk cycles.  Defaults assume 100 MHz clk (10 ns/cycle); the
//   datasheet number behind each one is in the comment beside it.
//
//   RESOLUTION NOTE: the burst runs in the sequencer clock domain, so transmit
//   edges quantise to 10 ns (t_drive = 10, t_dead = 4 -> 3.57 MHz rather than
//   3.50 MHz).  Fine so far.  The burst generator is confined to the S_FIRE_* /
//   S_DEAD_* states so it can later move to a 400-500 MHz MMCM domain or an
//   OSERDESE2 pattern without touching the rest of the FSM - if that happens,
//   the interlock must move with it and stay on the final output registers.
//////////////////////////////////////////////////////////////////////////////////

module tx_sequencer #(
    parameter integer F_SYS       = 100_000_000, // sequencer clock, Hz

    // ---- MAX14866 chain -----------------------------------------------------
    parameter integer SPI_HALF    = 5,        //  50 ns half period -> 10 MHz chain
                                              //     clock (f_CLK max 30 MHz)
    parameter integer CHAIN_BITS  = 64,       //  4 devices x 16 switches
    parameter integer T_CLR       = 20,       // 200 ns  (t_WC min 115 ns)
    parameter integer T_LE_LOW    = 5,        //  50 ns  (t_WL min   5 ns)
    parameter integer T_CS        = 2,        //  20 ns  (t_CS min   3 ns)

    // Floors for the two host-writable waits.  These are the datasheet limits,
    // not preferences - a host cannot be allowed to set a value that silently
    // breaks the part:
    //   below T_SETTLE_MIN  the switches have not finished moving when HV
    //                       arrives, and the analog node is not at ground
    //   below T_INHIBIT_MIN the MAX14866 transmit detector is still inhibiting
    //                       SPI, chain writes are DISCARDED WITH NO ERROR, and
    //                       the next shot fires into a stale element
    // Raise them here if you ever need to characterise below spec.
    parameter integer T_SETTLE_MIN  = 400,    // 4.00 us (t_ON / t_OFF max)
    parameter integer T_INHIBIT_MIN = 450,    // 4.50 us (SPI lockout after HV)

    // ---- MD1213 / TC6320 ----------------------------------------------------
    parameter integer T_OE_WAIT   = 100_000,  //   1 ms  gate coupling caps
                                              //         (10 nF x 10-50k, tau 100-500 us)

    // ---- housekeeping -------------------------------------------------------
    parameter integer WD_CYCLES   = 20_000_000, // 200 ms watchdog, per state
    parameter integer CHAIN_CHECK = 0,        //  1 = a mux_dout loopback mismatch
                                              //      raises a fault.  Keep 0 while
                                              //      DOUT is unconnected/floating.
    parameter integer N_ELEM      = 48,       // 3 branches x 16 channels
    parameter integer LIST_DEPTH  = 64        // element-list RAM depth
)(
    input  wire        clk,
    input  wire        rst,                   // synchronous, active high

    // ---- control ------------------------------------------------------------
    input  wire        arm,                   // level. Enables pulse_oe and firing.
    input  wire        start_frame,           // pulse. Run one frame.
    input  wire        continuous,            // level. Free-run frames.
    input  wire        fault_clr,             // pulse. Leave S_FAULT.

    // ---- runtime timing, clk cycles -----------------------------------------
    // One "cycle" is one +HV pulse and one -HV pulse, so cfg_n_cycles = N
    // produces N positive and N negative pulses.  Burst period per cycle is
    // 2*(cfg_t_drive + cfg_t_dead), i.e. f0 = F_SYS / (2*(t_drive + t_dead)).
    input  wire [7:0]  cfg_n_cycles,          // +/- pulse pairs per burst (>= 1)
    input  wire [15:0] cfg_t_drive,           // width of each +HV and -HV pulse
    input  wire [15:0] cfg_t_dead,            // idle gap between opposite polarities
    input  wire [23:0] cfg_t_settle,          // LE rising -> first HV edge
    input  wire [23:0] cfg_t_inhibit,         // last HV edge -> chain clocking
    input  wire [23:0] cfg_t_ring,            // ringdown blanking
    input  wire [23:0] cfg_t_rx,              // echo receive window

    // ---- element list -------------------------------------------------------
    input  wire        el_wr,
    input  wire [5:0]  el_wr_addr,
    input  wire [5:0]  el_wr_data,
    input  wire [6:0]  cfg_list_len,          // 1 .. LIST_DEPTH

    // ---- pins ---------------------------------------------------------------
    output wire        mux_clk,               // idle 0, shifts on rising edge
    output wire        mux_din,               // idle 0, MSB first
    output wire        mux_le,                // idle 1, ACTIVE LOW, transparent latch
    output wire        mux_clr,               // idle 0, ACTIVE HIGH, opens all switches
    input  wire        mux_dout,              // chain loopback, 64 clocks behind
    output wire        pulse_ina,             // idle 0, ACTIVE HIGH -> +HV
    output wire        pulse_inb,             // idle 1, ACTIVE LOW  -> -HV
    output wire        pulse_oe,              // idle 0, driver output enable
    output reg         tx_sync,               // 1-cycle pulse at start of burst

    // ---- status -------------------------------------------------------------
    output wire        busy,
    output reg  [5:0]  element_current,
    output reg         chain_ok,
    output wire        fault,
    output reg  [3:0]  fault_code,
    output reg  [15:0] frame_count,
    output wire [3:0]  dbg_state
);

    //==========================================================================
    // Sized / clamped copies of the parameters.  Every state below runs for
    // exactly N cycles by loading N-1 into a down counter, so a parameter of 0
    // would underflow into a multi-second wait.  Clamp to 1 here rather than
    // trusting whoever overrides them.
    //==========================================================================
    localparam integer T_CLR_C     = (T_CLR      < 1) ? 1 : T_CLR;
    localparam integer T_LE_LOW_C  = (T_LE_LOW   < 1) ? 1 : T_LE_LOW;
    localparam integer T_CS_C      = (T_CS       < 1) ? 1 : T_CS;
    localparam integer T_OE_WAIT_C = (T_OE_WAIT  < 1) ? 1 : T_OE_WAIT;
    localparam [23:0]  T_SETTLE_FL = (T_SETTLE_MIN  < 1) ? 1 : T_SETTLE_MIN;
    localparam [23:0]  T_INHIB_FL  = (T_INHIBIT_MIN < 1) ? 1 : T_INHIBIT_MIN;
    localparam [7:0]   SPI_HALF_C  = (SPI_HALF   < 1) ? 1 : SPI_HALF;
    localparam [6:0]   CHAIN_LAST  = CHAIN_BITS - 1;
    localparam [24:0]  WD_LIMIT    = WD_CYCLES;

    // ---- fault codes --------------------------------------------------------
    localparam [3:0] FC_NONE     = 4'd0,
                     FC_ELEMENT  = 4'd1,   // element out of range / not one-hot
                     FC_CHAIN    = 4'd2,   // mux_dout loopback mismatch
                     FC_WATCHDOG = 4'd3,   // a state exceeded WD_CYCLES
                     FC_SHOOT    = 4'd4;   // interlock saw ina & ~inb

    // ---- states -------------------------------------------------------------
    localparam [3:0] S_RST     = 4'd0,   // CLR asserted out of reset
                     S_SELFT   = 4'd1,   // shift 64 zeros - startup self-test
                     S_ARMW    = 4'd2,   // parked, waiting for arm
                     S_OEW     = 4'd3,   // OE up, gate caps settling
                     S_READY   = 4'd4,   // armed and idle
                     S_SHIFT   = 4'd5,   // 64 chain bits, LE high
                     S_WAITRX  = 4'd6,   // finish the previous receive window
                     S_TCS     = 4'd7,   // t_CS guard before LE falls
                     S_LATCH   = 4'd8,   // LE low, the switches change here
                     S_SETTLE  = 4'd9,   // t_ON / t_OFF
                     S_FIRE_P  = 4'd10,  // ina=1 inb=1 -> +HV
                     S_DEAD_A  = 4'd11,  // ina=0 inb=1 -> idle
                     S_FIRE_N  = 4'd12,  // ina=0 inb=0 -> -HV
                     S_DEAD_B  = 4'd13,  // ina=0 inb=1 -> idle
                     S_INHIBIT = 4'd14,  // SPI lockout after HV
                     S_FAULT   = 4'd15;

    reg [3:0] state = S_RST;
    assign dbg_state = state;

    //==========================================================================
    // Element list.  6-bit element index per entry, initialised 0 .. N_ELEM-1
    // so the sequencer walks the full aperture with no host interaction.
    // Distributed RAM, asynchronous read - the FSM has a whole element period
    // to use it.
    //==========================================================================
    (* ram_style = "distributed" *) reg [5:0] elem_list [0:LIST_DEPTH-1];
    integer li;
    initial for (li = 0; li < LIST_DEPTH; li = li + 1)
        elem_list[li] = (li < N_ELEM) ? li[5:0] : 6'd0;

    always @(posedge clk) if (el_wr) elem_list[el_wr_addr] <= el_wr_data;

    reg  [5:0] list_ptr = 6'd0;
    wire [6:0] list_len = (cfg_list_len == 7'd0) ? 7'd1 : cfg_list_len;
    wire       list_last = ({1'b0, list_ptr} == (list_len - 7'd1));
    wire [5:0] elem_sel = elem_list[list_ptr];

    //==========================================================================
    // Chain word for the selected element (sec 6).
    //   branch = e / 16      channel = e % 16
    //   word_ROOT       = 1 << branch     (SW0 / SW1 / SW2)
    //   word_BR[branch] = 1 << channel    the other two words are zero
    // Wire order is tail first - BR3, BR2, BR1, ROOT - MSB (SW15) first inside
    // each word.  Sending chain_word MSB first produces exactly that stream.
    //==========================================================================
    wire [1:0]  branch    = elem_sel[5:4];
    wire [3:0]  channel   = elem_sel[3:0];
    wire [15:0] onehot_ch = 16'h0001 << channel;

    wire [15:0] w_root = 16'h0001 << branch;
    wire [15:0] w_br1  = (branch == 2'd0) ? onehot_ch : 16'h0000;
    wire [15:0] w_br2  = (branch == 2'd1) ? onehot_ch : 16'h0000;
    wire [15:0] w_br3  = (branch == 2'd2) ? onehot_ch : 16'h0000;

    wire [63:0] chain_word = {w_br3, w_br2, w_br1, w_root};

    // Invariants.  Two closed ROOT channels short two branch buses together;
    // two closed branch channels put two elements in parallel across the
    // pulser.  Both are damaging, so check before the word can reach a latch.
    wire [15:0] w_br_all  = w_br1 | w_br2 | w_br3;
    wire [2:0]  br_nz     = {(w_br3 != 16'h0), (w_br2 != 16'h0), (w_br1 != 16'h0)};
    wire        root_1hot = (w_root  != 16'h0) && ((w_root  & (w_root  - 16'h1)) == 16'h0);
    wire        br_1hot   = (w_br_all != 16'h0) && ((w_br_all & (w_br_all - 16'h1)) == 16'h0);
    wire        root_rng  = (w_root[15:3] == 13'h0);        // SW0..SW2 only
    wire        br_single = (br_nz == 3'b001) || (br_nz == 3'b010) || (br_nz == 3'b100);
    wire        br_match  = (branch == 2'd0) ? (w_br1 != 16'h0) :
                            (branch == 2'd1) ? (w_br2 != 16'h0) :
                            (branch == 2'd2) ? (w_br3 != 16'h0) : 1'b0;
    wire        word_ok   = root_1hot && root_rng && br_1hot && br_single &&
                            br_match  && (elem_sel < N_ELEM);

    //==========================================================================
    // Pin output registers.  Reset state is exactly sec 7.1:
    //   clr = 1, oe = 0, ina = 0, inb = 1, le = 1, clk = 0, din = 0
    //==========================================================================
    reg clk_r = 1'b0;
    reg din_r = 1'b0;
    reg le_r  = 1'b1;
    reg clr_r = 1'b1;
    reg ina_r = 1'b0;
    reg inb_r = 1'b1;
    reg oe_r  = 1'b0;

    //==========================================================================
    // Chain shifter.  Owns mux_clk / mux_din outright, so nothing else in the
    // design can put an edge on the chain clock.  One bit per 2*SPI_HALF
    // cycles:
    //   rising edge  -> the MAX14866 samples DIN, and we sample DOUT
    //   falling edge -> we present the next DIN (t_DS / t_DH)
    //
    // DOUT is sampled ON the rising edge, not after it.  The chain is 64 flops
    // deep and each device clocks its DOUT off the same edge, so the first bit
    // of the previous word is already sitting on DOUT *before* the first rising
    // edge of this shift.  Sampling after each edge would miss it and shift the
    // captured word by one bit.  Sampling on the edge gives sample k = the
    // value present before edge k, i.e. exactly the previous 64-bit word.
    //
    // The two synchroniser stages mean we actually read the pin 20 ns before
    // the edge.  DOUT settles t_DO (20 ns max) after the *previous* edge, which
    // is 100 ns earlier, so the sample point has 60 ns of margin.
    //==========================================================================
    (* ASYNC_REG = "TRUE" *) reg [1:0] dout_sync = 2'b00;
    always @(posedge clk) dout_sync <= {dout_sync[0], mux_dout};

    reg [63:0] tx_sr      = 64'h0;
    reg [63:0] rx_sr      = 64'h0;
    reg [63:0] prev_word  = 64'h0;   // what we sent last time - DOUT lags 64 clocks
    reg [6:0]  bit_cnt    = 7'd0;
    reg [7:0]  div_cnt    = 8'd0;
    reg        shift_busy = 1'b0;
    reg        shift_done = 1'b0;

    reg        shift_start = 1'b0;   // driven by the FSM
    reg [63:0] shift_data  = 64'h0;

    // Available on the shift_done cycle, before chain_ok has been registered.
    wire chain_match = (rx_sr == prev_word);

    always @(posedge clk) begin
        shift_done <= 1'b0;

        if (rst) begin
            shift_busy <= 1'b0;
            clk_r      <= 1'b0;
            din_r      <= 1'b0;
            bit_cnt    <= 7'd0;
            div_cnt    <= 8'd0;
            tx_sr      <= 64'h0;
            rx_sr      <= 64'h0;
            prev_word  <= 64'h0;
            chain_ok   <= 1'b1;
        end else begin
            if (shift_start) begin
                tx_sr      <= {shift_data[62:0], 1'b0};
                din_r      <= shift_data[63];        // first bit onto the wire
                rx_sr      <= 64'h0;
                bit_cnt    <= 7'd0;
                div_cnt    <= SPI_HALF_C - 8'd1;
                clk_r      <= 1'b0;
                shift_busy <= 1'b1;
            end else if (shift_busy) begin
                if (div_cnt != 8'd0) begin
                    div_cnt <= div_cnt - 8'd1;
                end else begin
                    div_cnt <= SPI_HALF_C - 8'd1;
                    if (!clk_r) begin
                        clk_r <= 1'b1;               // rising edge - device samples DIN
                        rx_sr <= {rx_sr[62:0], dout_sync[1]};
                    end else begin
                        clk_r <= 1'b0;               // falling edge
                        if (bit_cnt == CHAIN_LAST) begin
                            shift_busy <= 1'b0;
                            shift_done <= 1'b1;
                            din_r      <= 1'b0;      // chain data idles low
                        end else begin
                            bit_cnt <= bit_cnt + 7'd1;
                            tx_sr   <= {tx_sr[62:0], 1'b0};
                            din_r   <= tx_sr[63];    // next bit, on the falling edge
                        end
                    end
                end
            end

            // Loopback: DOUT mirrors DIN delayed by exactly 64 clocks, so the
            // word captured while shifting frame N is frame N-1.  After POR the
            // MAX14866 registers are zero, so the first readback is 64 zeros -
            // a free confirmation that all four parts are alive.
            if (shift_done) begin
                chain_ok  <= chain_match;
                prev_word <= shift_data;
            end
        end
    end

    //==========================================================================
    // Burst shape.  Driven phase = t_half - t_dead, clamped so both the driven
    // and the dead phase are always at least one cycle long.
    //==========================================================================
    wire [15:0] t_dead_eff  = (cfg_t_dead  == 16'd0) ? 16'd1 : cfg_t_dead;
    wire [15:0] t_drive_eff = (cfg_t_drive == 16'd0) ? 16'd1 : cfg_t_drive;
    wire [7:0]  n_cyc_eff   = (cfg_n_cycles == 8'd0) ? 8'd1 : cfg_n_cycles;

    // Host-writable waits, floored at their datasheet minima.  The clamp is
    // deliberately here in the sequencer rather than in the host: a bad value
    // arriving over USB must not be able to break the MAX14866, and the
    // t_inhibit failure mode in particular is silent.
    wire [23:0] t_settle_eff  = (cfg_t_settle  < T_SETTLE_FL) ? T_SETTLE_FL : cfg_t_settle;
    wire [23:0] t_inhibit_eff = (cfg_t_inhibit < T_INHIB_FL)  ? T_INHIB_FL  : cfg_t_inhibit;

    // Receive window, saturating so an oversized pair of settings cannot wrap
    // the counter and cut the window short.
    wire [24:0] rx_sum = {1'b0, cfg_t_ring} + {1'b0, cfg_t_rx};
    wire [23:0] rx_win = rx_sum[24] ? 24'hFF_FFFF : rx_sum[23:0];

    //==========================================================================
    // Sequencer
    //==========================================================================
    reg [23:0] tmr           = T_CLR_C - 1; // general state timer (CLR out of POR)
    reg [15:0] btmr          = 16'd0;   // burst phase timer
    reg [7:0]  cyc_cnt       = 8'd0;    // HV cycles remaining
    reg [23:0] rx_tmr        = 24'd0;   // receive window, from the end of the burst
    reg [24:0] wd_cnt        = 25'd0;   // per-state watchdog
    reg [5:0]  elem_pend     = 6'd0;    // element sitting in the shift register
    reg        word_ok_pend  = 1'b1;    // its one-hot check result
    reg        last_of_frame = 1'b0;
    reg        run           = 1'b0;    // a frame is in progress
    reg        fault_r       = 1'b0;

    assign fault = fault_r;
    assign busy  = (state >= S_SHIFT) && (state != S_FAULT);

    // Watchdog.  Only runs while a transmit event is in progress - S_ARMW and
    // S_READY are legitimately open ended.  Cleared on every state change.
    reg [3:0] state_d = S_RST;
    always @(posedge clk) state_d <= state;
    wire wd_hit = busy && (wd_cnt >= WD_LIMIT);

    always @(posedge clk) begin
        if (rst || !busy || (state != state_d)) wd_cnt <= 25'd0;
        else                                    wd_cnt <= wd_cnt + 25'd1;
    end

    // Latch a start request so a one-cycle pulse is never missed.
    reg start_pend = 1'b0;
    always @(posedge clk) begin
        if (rst)                                       start_pend <= 1'b0;
        else if (start_frame)                          start_pend <= 1'b1;
        else if ((state == S_READY) && arm && !fault_r) start_pend <= 1'b0;
    end

    // Shoot-through detection, for the fault latch.  The FSM never produces
    // this combination; the interlock at the bottom blocks it regardless.
    wire shoot_through = ina_r & ~inb_r;

    // Fault sources, ordered most urgent first.
    reg       trip;
    reg [3:0] trip_code;
    always @* begin
        trip      = 1'b0;
        trip_code = FC_NONE;
        if (state != S_FAULT) begin
            if (shoot_through) begin
                trip = 1'b1;  trip_code = FC_SHOOT;
            end else if (wd_hit) begin
                trip = 1'b1;  trip_code = FC_WATCHDOG;
            end else if (!word_ok_pend &&
                         ((state == S_SHIFT) || (state == S_WAITRX) || (state == S_TCS))) begin
                trip = 1'b1;  trip_code = FC_ELEMENT;
            end else if ((CHAIN_CHECK != 0) && shift_done && !chain_match &&
                         ((state == S_SHIFT) || (state == S_SELFT))) begin
                trip = 1'b1;  trip_code = FC_CHAIN;
            end
        end
    end

    // arm going away is a clean disarm, not a latched fault: park the outputs,
    // drop OE, assert CLR, and go back to waiting for arm (sec 3 / sec 7.5).
    wire disarm = !arm && (state != S_RST) && (state != S_SELFT) &&
                          (state != S_ARMW) && (state != S_FAULT);

    always @(posedge clk) begin
        shift_start <= 1'b0;
        tx_sync     <= 1'b0;

        // Receive window free-runs from the end of the burst, through
        // S_INHIBIT and S_SHIFT, so the shift lands early in the RX window.
        if (rx_tmr != 24'd0) rx_tmr <= rx_tmr - 24'd1;

        if (rst) begin
            state           <= S_RST;
            tmr             <= T_CLR_C - 1;
            clr_r           <= 1'b1;
            le_r            <= 1'b1;
            ina_r           <= 1'b0;
            inb_r           <= 1'b1;
            oe_r            <= 1'b0;
            rx_tmr          <= 24'd0;
            btmr            <= 16'd0;
            cyc_cnt         <= 8'd0;
            list_ptr        <= 6'd0;
            elem_pend       <= 6'd0;
            word_ok_pend    <= 1'b1;
            last_of_frame   <= 1'b0;
            run             <= 1'b0;
            fault_r         <= 1'b0;
            fault_code      <= FC_NONE;
            frame_count     <= 16'd0;
            element_current <= 6'd0;
        end else if (trip) begin
            // 1. park the driver, 2. CLR every switch, 3. drop OE, 4. latch.
            ina_r      <= 1'b0;
            inb_r      <= 1'b1;
            oe_r       <= 1'b0;
            clr_r      <= 1'b1;
            le_r       <= 1'b1;
            run        <= 1'b0;
            rx_tmr     <= 24'd0;
            fault_r    <= 1'b1;
            fault_code <= trip_code;
            state      <= S_FAULT;
        end else if (disarm) begin
            ina_r  <= 1'b0;
            inb_r  <= 1'b1;
            oe_r   <= 1'b0;
            clr_r  <= 1'b1;
            le_r   <= 1'b1;
            run    <= 1'b0;
            rx_tmr <= 24'd0;
            tmr    <= T_CLR_C - 1;
            state  <= S_RST;
        end else begin
            case (state)

            //------------------------------------------------------------------
            // Power-up / recovery: hold CLR for >= t_WC, then release.
            //------------------------------------------------------------------
            S_RST: begin
                clr_r <= 1'b1;
                le_r  <= 1'b1;
                ina_r <= 1'b0;
                inb_r <= 1'b1;
                oe_r  <= 1'b0;
                if (tmr != 24'd0) begin
                    tmr <= tmr - 24'd1;
                end else if (!shift_busy) begin
                    clr_r        <= 1'b0;            // release CLR, then self-test
                    shift_data   <= 64'h0;
                    shift_start  <= 1'b1;
                    word_ok_pend <= 1'b1;            // zeros are not an element word
                    state        <= S_SELFT;
                end
            end

            //------------------------------------------------------------------
            // Startup self-test: 64 zeros out, 64 zeros back.  LE never pulses
            // here, so the switches stay open whatever happens.
            //------------------------------------------------------------------
            S_SELFT: if (shift_done) state <= S_ARMW;

            //------------------------------------------------------------------
            // Parked.  On arm, raise OE once and let the 10 nF gate coupling
            // caps settle before the first shot.
            //------------------------------------------------------------------
            S_ARMW: begin
                oe_r <= 1'b0;
                if (arm) begin
                    oe_r  <= 1'b1;
                    tmr   <= T_OE_WAIT_C - 1;
                    state <= S_OEW;
                end
            end

            S_OEW: if (tmr != 24'd0) tmr <= tmr - 24'd1;
                   else              state <= S_READY;

            //------------------------------------------------------------------
            // Armed and idle.
            //------------------------------------------------------------------
            // list_ptr is forced to 0 here; wait for that to land so chain_word
            // is guaranteed to describe element 0 before the shift is issued.
            S_READY: begin
                list_ptr <= 6'd0;
                rx_tmr   <= 24'd0;
                if ((continuous || start_pend) && (list_ptr == 6'd0)) begin
                    shift_data    <= chain_word;
                    shift_start   <= 1'b1;
                    elem_pend     <= elem_sel;
                    word_ok_pend  <= word_ok;
                    last_of_frame <= (list_len == 7'd1);
                    run           <= 1'b1;
                    state         <= S_SHIFT;
                end
            end

            //------------------------------------------------------------------
            // 64 chain bits.  LE stays high the whole time.  This overlaps the
            // previous element's receive window (rx_tmr is still counting).
            //------------------------------------------------------------------
            S_SHIFT: if (shift_done) begin
                list_ptr <= list_last ? 6'd0 : (list_ptr + 6'd1);
                state    <= S_WAITRX;
            end

            //------------------------------------------------------------------
            // Wait out the rest of the previous receive window.  The register
            // holds the new element; the switches have not moved.
            //------------------------------------------------------------------
            S_WAITRX: if (rx_tmr == 24'd0) begin
                if (!run) begin
                    state <= S_READY;                // frame finished, draining done
                end else begin
                    tmr   <= T_CS_C - 1;
                    state <= S_TCS;
                end
            end

            S_TCS: if (tmr != 24'd0) tmr <= tmr - 24'd1;
                   else begin
                       le_r  <= 1'b0;                // switches change here
                       tmr   <= T_LE_LOW_C - 1;
                       state <= S_LATCH;
                   end

            S_LATCH: if (tmr != 24'd0) tmr <= tmr - 24'd1;
                     else begin
                         le_r            <= 1'b1;
                         element_current <= elem_pend;
                         tmr             <= t_settle_eff - 24'd1;
                         state           <= S_SETTLE;
                     end

            //------------------------------------------------------------------
            // t_ON / t_OFF.  The analog node must be quiet at ground for this
            // entire interval - nothing else may happen here.
            //------------------------------------------------------------------
            S_SETTLE: if (tmr != 24'd0) tmr <= tmr - 24'd1;
                      else begin
                          cyc_cnt <= n_cyc_eff;
                          btmr    <= t_drive_eff - 16'd1;
                          ina_r   <= 1'b1;           // ina 0->1 only: idle -> +HV
                          tx_sync <= 1'b1;
                          state   <= S_FIRE_P;
                      end

            //------------------------------------------------------------------
            // Burst.  Exactly one of ina / inb changes at every transition.
            //------------------------------------------------------------------
            S_FIRE_P: if (btmr != 16'd0) btmr <= btmr - 16'd1;
                      else begin
                          ina_r <= 1'b0;             // +HV -> idle
                          btmr  <= t_dead_eff - 16'd1;
                          state <= S_DEAD_A;
                      end

            S_DEAD_A: if (btmr != 16'd0) btmr <= btmr - 16'd1;
                      else begin
                          inb_r <= 1'b0;             // idle -> -HV
                          btmr  <= t_drive_eff - 16'd1;
                          state <= S_FIRE_N;
                      end

            S_FIRE_N: if (btmr != 16'd0) btmr <= btmr - 16'd1;
                      else begin
                          inb_r <= 1'b1;             // -HV -> idle
                          btmr  <= t_dead_eff - 16'd1;
                          state <= S_DEAD_B;
                      end

            S_DEAD_B: if (btmr != 16'd0) begin
                          btmr <= btmr - 16'd1;
                      end else if (cyc_cnt > 8'd1) begin
                          cyc_cnt <= cyc_cnt - 8'd1;
                          ina_r   <= 1'b1;           // idle -> +HV, next cycle
                          btmr    <= t_drive_eff - 16'd1;
                          state   <= S_FIRE_P;
                      end else begin
                          // burst complete, parked in the idle state
                          rx_tmr <= rx_win;
                          tmr    <= t_inhibit_eff - 24'd1;
                          state  <= S_INHIBIT;
                      end

            //------------------------------------------------------------------
            // MAX14866 transmit detector: SPI writes in this window are
            // silently discarded.  No chain activity until it expires.
            //------------------------------------------------------------------
            S_INHIBIT: if (tmr != 24'd0) begin
                tmr <= tmr - 24'd1;
            end else begin
                if (last_of_frame) frame_count <= frame_count + 16'd1;
                if (last_of_frame && !continuous) begin
                    run   <= 1'b0;                   // drain the RX window, then stop
                    state <= S_WAITRX;
                end else begin
                    shift_data    <= chain_word;     // list_ptr already advanced
                    shift_start   <= 1'b1;
                    elem_pend     <= elem_sel;
                    word_ok_pend  <= word_ok;
                    last_of_frame <= list_last;
                    state         <= S_SHIFT;
                end
            end

            //------------------------------------------------------------------
            // Latched fault.  CLR stays asserted - every switch open - and the
            // shift register keeps its contents, so recovery needs one LE pulse
            // and no reload.
            //------------------------------------------------------------------
            S_FAULT: begin
                ina_r <= 1'b0;
                inb_r <= 1'b1;
                oe_r  <= 1'b0;
                clr_r <= 1'b1;
                le_r  <= 1'b1;
                if (fault_clr) begin
                    fault_r    <= 1'b0;
                    fault_code <= FC_NONE;
                    tmr        <= T_CLR_C - 1;
                    state      <= S_RST;
                end
            end

            default: state <= S_RST;

            endcase
        end
    end

    //==========================================================================
    // Output stage.
    //
    // The interlock is unconditional and independent of the FSM: it sits
    // between the output registers and the pins and cannot be bypassed.  The
    // forbidden condition is ina & ~inb.  The board also carries a discrete
    // gate-level interlock; both exist, neither substitutes for the other.
    //
    // Only one of ina_r / inb_r ever changes per clock edge, so this LUT
    // cannot produce a decoding glitch of its own.
    //==========================================================================
    assign pulse_ina = shoot_through ? 1'b0 : ina_r;
    assign pulse_inb = shoot_through ? 1'b1 : inb_r;
    assign pulse_oe  = arm & oe_r & ~shoot_through & ~fault_r;

    assign mux_clk = clk_r;
    assign mux_din = din_r;
    assign mux_le  = le_r;
    assign mux_clr = clr_r;

endmodule
