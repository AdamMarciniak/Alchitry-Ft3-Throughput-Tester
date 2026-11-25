`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: tx_sequencer
// Description: Sonic transmit sequencer - MAX14866 tree-mux daisy chain +
//              MD1213 driver / TC6320 bipolar HV pulser.
//
//   One transmit event per element:
//     S_SHIFT  -> 64 chain bits, LE high.  The receive window is already over.
//     S_TCS    -> t_CS guard, last CLK rising edge to LE falling
//     S_LATCH  -> LE low, the switches move here
//     S_SETTLE -> t_ON / t_OFF, analog node quiet at ground
//     S_FIRE_* -> n_cycles of  +HV / idle / -HV / idle  (return to zero)
//     S_INHIBIT-> MAX14866 SPI lockout after HV, overlapped with the RX window
//     S_WAITRX -> the rest of the receive window, then issue the next shift
//
//   RX QUIET WINDOW: the chain shift used to overlap the receive window - it
//   was issued from S_INHIBIT and ran early in the window, where the echo is
//   ringdown-dominated anyway.  It does not any more.  64 MAX14866 clock edges
//   are 64 chances to couple digital switching into the element that is at that
//   moment connected to the receive path, and the RX window is exactly where
//   that costs the most, so the shift now waits for the window to close: the
//   whole of S_INHIBIT + S_WAITRX is a dead interval with no chain clocking, no
//   DIN transitions and no LE movement.  It costs one shift time per element -
//   CHAIN_BITS * 2 * SPI_HALF cycles, 6.4 us with the defaults - added to the
//   element period, i.e. frame rate, and that is the intended trade.
//
//   CODED EXCITATION (chirp): the burst engine runs in HALF cycles - one
//   half cycle is one driven phase (+HV or -HV) plus the dead gap after it.
//   cfg_chirp_len = 0 reproduces the fixed burst exactly: 2*n_cycles half
//   cycles, every driven phase cfg_t_drive long.  cfg_chirp_len = M > 0 fires
//   M half cycles whose driven widths come from a host-loaded table instead,
//   one entry per half cycle, so the period can sweep across the burst (a
//   linear-FM chirp is the intended use; any monotonic or non-monotonic sweep
//   that fits 256 entries works).  Polarity still strictly alternates
//   +,-,+,... and the dead gap is still cfg_t_dead everywhere: the table
//   holds only the driven widths, so no table content can express a polarity
//   violation - the electrical rules below survive any garbage the host
//   uploads, and a zero entry is clamped to one cycle.
//
//   ELEMENT NUMBERING: everything outside the mux_code() table below speaks in
//   APERTURE POSITIONS - 0 is the left-most element of the array, N_ELEM-1 the
//   right-most.  That is what the element list holds, what element_current
//   reports, and therefore what the host header carries.  mux_code() is the
//   single place the connector's scrambled wiring is described.
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

    // Floors for host-writable waits.  These are the datasheet limits,
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
    parameter integer T_DEAD_MIN  = 4,        // 40 ns: TC6320 t_d(OFF)+t_f=35 ns
    parameter integer T_OE_WAIT   = 100_000,  //   1 ms  gate coupling caps
                                              //         (10 nF x 10-50k, tau 100-500 us)

    // ---- housekeeping -------------------------------------------------------
    parameter integer WD_CYCLES   = 20_000_000, // 200 ms watchdog, per state
    parameter integer CHAIN_CHECK = 0,        //  1 = a mux_dout loopback mismatch
                                              //      raises a fault.  Keep 0 while
                                              //      DOUT is unconnected/floating.
    parameter integer N_ELEM      = 48,       // 3 branches x 16 channels
    parameter integer LIST_DEPTH  = 64,       // element-list RAM depth

    // ---- chain topology -----------------------------------------------------
    // Which ROOT switch feeds each leaf mux.  SWn is COMn->NOn (datasheet
    // Table 1 / pin map), so these are the root NO pins the leaves hang off -
    // NO5, NO7, NO11 on this board, NOT SW0/SW1/SW2.
    parameter integer ROOT_SW_BR0 = 5,        // root -> BR1 (chain device 1)
    parameter integer ROOT_SW_BR1 = 7,        // root -> BR2 (chain device 2)
    parameter integer ROOT_SW_BR2 = 11,       // root -> BR3 (chain device 3)

    // ---- static-mux bench mode ----------------------------------------------
    // 1 = ignore the element list when building the chain word and hold one
    // fixed root + leaf pair closed for every shot.  The FSM is untouched:
    // same shift, same LE pulse, same settle / burst / inhibit / RX timing,
    // same elements per frame - every element just writes the SAME word, so
    // the switches are reloaded with the value they already have and never
    // actually move.  Pulse and receive on one element, through one path.
    // These three are HARDWARE coordinates - chain device and NO pin - not an
    // aperture position, so they bypass mux_code() entirely.
    parameter integer MUX_STATIC      = 0,    // 0 = walk the aperture (normal)
    parameter integer MUX_STATIC_ROOT = 5,    // root switch held closed (SW5)
    parameter integer MUX_STATIC_BR   = 0,    // leaf: 0 = BR1, 1 = BR2, 2 = BR3
    parameter integer MUX_STATIC_CH   = 10    // leaf switch held closed (SW10)
)(
    input  wire        clk,
    input  wire        rst,                   // synchronous, active high

    // ADC sample-grid phase from afe_stream: toggles once every 8 samples
    // (200 ns), always at the same point of the FIFO pair/word grid.  The
    // burst launch holds for an edge of this so the capture start (slaved to
    // tx_sync, quantised to a 50 ns word boundary by the async ADC) sits at a
    // CONSTANT offset instead of a uniform 0-50 ns per-element error.
    input  wire        adc_sync_tog,
    input  wire        capture_ready,         // ctrl_decode, same clk domain

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
    input  wire [1:0]  cfg_method,     // 0 legacy, 1 Golay A/B, 2 paired neighbor, 3 center/left/right RX
    output wire [1:0]  shot_kind,      // captured at tx_sync
    input  wire [7:0]  cfg_chirp_len,         // half cycles from the chirp table;
                                              //   0 = fixed burst (n_cycles/t_drive)

    // ---- chirp table --------------------------------------------------------
    // One driven-phase width per half cycle, clk cycles.  Written any time;
    // only read between S_SETTLE and the end of the burst, so a mid-burst
    // write can at worst perturb the burst being fired, never the FSM.
    input  wire        ch_wr,
    input  wire [7:0]  ch_wr_addr,
    input  wire [15:0] ch_wr_data,
    input  wire [23:0] cfg_t_settle,          // LE rising -> first HV edge
    input  wire [23:0] cfg_t_inhibit,         // last HV edge -> chain clocking
    input  wire [23:0] cfg_t_ring,            // ringdown blanking
    input  wire [23:0] cfg_t_rx,              // echo receive window

    // ---- element list -------------------------------------------------------
    input  wire        el_wr,
    input  wire [5:0]  el_wr_addr,
    input  wire [5:0]  el_wr_data,
    input  wire [6:0]  cfg_list_len,          // 1 .. LIST_DEPTH

    // ---- per-element transmit trim ------------------------------------------
    // One 12-bit clk-cycle delay per ELEMENT (not per list slot - the trim is a
    // property of the wiring and the crystal, so it must follow the element
    // wherever the list puts it).  See the trim table below for what it fixes.
    input  wire        tr_wr,
    input  wire [5:0]  tr_wr_addr,            // element index 0 .. LIST_DEPTH-1
    input  wire [11:0] tr_wr_data,            // clk cycles, 10 ns each

    // ---- pins ---------------------------------------------------------------
    output wire        mux_clk,               // idle 0, shifts on rising edge
    output wire        mux_din,               // idle 0, MSB first
    output wire        mux_le,                // idle 1, ACTIVE LOW, transparent latch
    output wire        mux_clr,               // idle 0, ACTIVE HIGH, opens all switches
    input  wire        mux_dout,              // chain loopback, 64 clocks behind
    output wire        pulse_ina,             // idle 0, ACTIVE HIGH -> +HV
    output wire        pulse_inb,             // idle 1, ACTIVE LOW  -> -HV
    output wire        pulse_oe,              // idle 0, driver output enable
    output reg         tx_sync,               // 1-cycle pulse, ADC grid tick that
                                              // OPENS this element's capture -
                                              // trim cycles before the HV edge

    // ---- status -------------------------------------------------------------
    output wire        busy,
    output reg  [5:0]  element_current,
    output reg         chain_ok,          // last readback matched what was sent

    // ---- chain loopback diagnostics -----------------------------------------
    // mux_dout IS connected on this board (K5 / header B33 / DOUT_READBACK), so
    // every shift verifies the PREVIOUS shift at no cost.  These report that
    // without stopping the run; CHAIN_CHECK turns the same event into a latched
    // fault, which is the wrong behaviour while diagnosing - it parks the
    // sequencer on the first mismatch instead of letting it keep failing where
    // it can be watched.
    output reg  [15:0] chain_err_cnt,     // mismatches since reset (saturating)
    output reg  [5:0]  chain_err_elem,    // element whose word failed to survive
    output reg  [63:0] chain_err_word,    // what came back instead
    output reg         chain_err_stb,     // 1-cycle pulse per mismatch

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
    localparam [15:0]  T_DEAD_FL   = (T_DEAD_MIN < 1) ? 1 : T_DEAD_MIN;
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
                     S_WAITRX  = 4'd6,   // finish the receive window, then shift
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
    // Element list.  One 6-bit APERTURE POSITION per entry (0 = left-most
    // element, N_ELEM-1 = right-most), initialised 0 .. N_ELEM-1 so the
    // sequencer sweeps the array left to right with no host interaction.  The
    // mux_code() table below turns a position into the (branch, channel) the
    // wiring actually puts it on; nothing outside that table needs to know the
    // connector order.  Distributed RAM, asynchronous read - the FSM has a
    // whole element period to use it.
    //==========================================================================
    (* ram_style = "distributed" *) reg [5:0] elem_list [0:LIST_DEPTH-1];
    integer li;
    initial for (li = 0; li < LIST_DEPTH; li = li + 1)
        elem_list[li] = (li < N_ELEM) ? li[5:0] : 6'd0;

    always @(posedge clk) if (el_wr) elem_list[el_wr_addr] <= el_wr_data;

    //==========================================================================
    // PER-ELEMENT TRANSMIT TRIM
    //
    // What it fixes: with the burst pinned to the ADC grid (adc_tick, below)
    // the sweep-to-sweep jitter is down to a few ns, but the elements do not
    // all sit at the same PHASE - measured on the artifact, their zero
    // crossings differ element to element, and that difference is static.
    // Cable, mux branch, and the element's own acoustic response all land in
    // it.  A static per-element phase error is a defocus the beamformer cannot
    // see, and coherence factor punishes it on the target as hard as on the
    // clutter, so it is worth a calibration table.
    //
    // Why it trims the TRANSMIT and not the range gate: adding the trim to
    // seq_dly (ctrl_decode's S_DLY) looks like the obvious place and does not
    // work.  Outside S_RX the ADC FIFO is drained and discarded, so the gate
    // effectively opens on the next 40 MSPS WORD boundary - a 10 ns trim there
    // quantises to 50 ns, two whole samples, which is coarser than the error
    // being corrected.  Delaying the HV edge instead leaves the gate pinned to
    // the grid where sync_tog put it, and moves the pulse inside the window in
    // clean 10 ns steps.  Bigger trim = this element fires later = its artifact
    // and all of its echoes sit LATER (deeper) in the window.
    //
    // 12 bits = 0..40.95 us.  Calibration needs a few hundred ns; the rest of
    // the range is headroom for using the same table as a transmit focal law
    // later.  The trim only ever LENGTHENS the settle wait, so T_SETTLE_MIN is
    // untouched by any value a host can write.
    //==========================================================================
    (* ram_style = "distributed" *) reg [11:0] trim_tab [0:LIST_DEPTH-1];
    integer ti;
    initial for (ti = 0; ti < LIST_DEPTH; ti = ti + 1) trim_tab[ti] = 12'd0;

    always @(posedge clk) if (tr_wr) trim_tab[tr_wr_addr] <= tr_wr_data;

    // element_current is loaded on entry to S_SETTLE, so this asynchronous read
    // has the whole settle wait - microseconds - to resolve before it is used.
    wire [11:0] trim_sel = trim_tab[element_current];

    //==========================================================================
    // Chirp table.  256 driven-phase widths, one per half cycle, distributed
    // RAM with asynchronous read - the index is stable for a whole dead gap
    // (>= t_dead >= 1 cycle) before the value is loaded into the burst timer,
    // so the async read path has an entire clock period of slack.  Initialised
    // to the default t_drive so an unloaded table fires something sane.
    //==========================================================================
    (* ram_style = "distributed" *) reg [15:0] chirp_ram [0:255];
    integer ci;
    initial for (ci = 0; ci < 256; ci = ci + 1) chirp_ram[ci] = 16'd10;

    always @(posedge clk) if (ch_wr) chirp_ram[ch_wr_addr] <= ch_wr_data;

    reg  [5:0] list_ptr = 6'd0;
    wire [6:0] list_len = (cfg_list_len == 7'd0) ? 7'd1 : cfg_list_len;
    wire       list_last = ({1'b0, list_ptr} == (list_len - 7'd1));
    wire [5:0] elem_sel = elem_list[list_ptr];

    //==========================================================================
    // Aperture position -> mux hardware address.
    //
    // elem_list holds an APERTURE POSITION: 0 is the left-most element of the
    // array, 47 the right-most.  That is also what element_current reports, so
    // the header the host sees is a position along the probe face and indexes
    // the geometry table in tfm_gl_host.py directly.  The mux tree is NOT wired
    // in that order - the connector scrambles it - so this table is the one
    // place the physical wiring is described.
    //
    // Two independent renumberings are folded in here.  Get either wrong and
    // the image is a shuffled version of the tissue, which looks plausible:
    //
    //  1. The board's pin labels are off by one device from our chain
    //     numbering.  Chain order is ROOT, mux1, mux2, mux3 (root nearest the
    //     FPGA), i.e. mux1 = BR1 = branch 0, mux2 = BR2 = branch 1,
    //     mux3 = BR3 = branch 2.  But a pin printed "1Nxx" lands on mux 3,
    //     "2Nxx" on mux 1 and "3Nxx" on mux 2.  So:
    //         label 1Nxx -> BR3 -> branch 2      (A*/B* elements)
    //         label 2Nxx -> BR1 -> branch 0      (G*/H* elements)
    //         label 3Nxx -> BR2 -> branch 1      (C*/D*/E*/F* elements)
    //     The channel number carries straight through: Nxx -> SWxx.
    //
    //  2. Within a device the NO pins are not in array order either - e.g. the
    //     four left-most elements A1 A2 B1 B2 are BR3 SW15, SW14, SW3, SW2.
    //
    // The result is a permutation: every one of the 48 (branch, channel) pairs
    // appears exactly once, 16 per branch.  The label beside each entry is the
    // silkscreen name of that element, kept here so the table can be checked
    // against the connector drawing without re-deriving anything.
    //
    // Positions >= N_ELEM cannot occur - word_ok gates on elem_sel < N_ELEM and
    // faults FC_ELEMENT before the word can be latched - so the default arm is
    // unreachable and exists only to keep the function fully specified.
    //==========================================================================
    function [5:0] mux_code;                // {branch[1:0], channel[3:0]}
        input [5:0] pos;
        begin
            case (pos)
            // ---- 1Nxx pins -> BR3 (branch 2) --------------------------------
            6'd0 : mux_code = {2'd2, 4'd15};   // A1
            6'd1 : mux_code = {2'd2, 4'd14};   // A2
            6'd2 : mux_code = {2'd2, 4'd3 };   // B1
            6'd3 : mux_code = {2'd2, 4'd2 };   // B2
            6'd4 : mux_code = {2'd2, 4'd13};   // A3
            6'd5 : mux_code = {2'd2, 4'd12};   // A4
            6'd6 : mux_code = {2'd2, 4'd1 };   // B3
            6'd7 : mux_code = {2'd2, 4'd0 };   // B4
            // ---- 3Nxx pins -> BR2 (branch 1) --------------------------------
            6'd8 : mux_code = {2'd1, 4'd15};   // C5
            6'd9 : mux_code = {2'd1, 4'd14};   // C6
            6'd10: mux_code = {2'd1, 4'd11};   // D5
            6'd11: mux_code = {2'd1, 4'd10};   // D6
            6'd12: mux_code = {2'd1, 4'd13};   // C7
            6'd13: mux_code = {2'd1, 4'd12};   // C8
            6'd14: mux_code = {2'd1, 4'd9 };   // D7
            6'd15: mux_code = {2'd1, 4'd8 };   // D8
            // ---- 1Nxx pins -> BR3 (branch 2) --------------------------------
            6'd16: mux_code = {2'd2, 4'd11};   // A5
            6'd17: mux_code = {2'd2, 4'd10};   // A6
            6'd18: mux_code = {2'd2, 4'd4 };   // B5
            6'd19: mux_code = {2'd2, 4'd5 };   // B6
            6'd20: mux_code = {2'd2, 4'd9 };   // A7
            6'd21: mux_code = {2'd2, 4'd8 };   // A8
            6'd22: mux_code = {2'd2, 4'd6 };   // B7
            6'd23: mux_code = {2'd2, 4'd7 };   // B8
            // ---- 2Nxx pins -> BR1 (branch 0) --------------------------------
            6'd24: mux_code = {2'd0, 4'd7 };   // H24
            6'd25: mux_code = {2'd0, 4'd6 };   // H23
            6'd26: mux_code = {2'd0, 4'd8 };   // G24
            6'd27: mux_code = {2'd0, 4'd9 };   // G23
            6'd28: mux_code = {2'd0, 4'd5 };   // H22
            6'd29: mux_code = {2'd0, 4'd4 };   // H21
            6'd30: mux_code = {2'd0, 4'd10};   // G22
            6'd31: mux_code = {2'd0, 4'd11};   // G21
            // ---- 3Nxx pins -> BR2 (branch 1) --------------------------------
            6'd32: mux_code = {2'd1, 4'd3 };   // F24
            6'd33: mux_code = {2'd1, 4'd2 };   // F23
            6'd34: mux_code = {2'd1, 4'd7 };   // E24
            6'd35: mux_code = {2'd1, 4'd6 };   // E23
            6'd36: mux_code = {2'd1, 4'd1 };   // F22
            6'd37: mux_code = {2'd1, 4'd0 };   // F21
            6'd38: mux_code = {2'd1, 4'd5 };   // E22
            6'd39: mux_code = {2'd1, 4'd4 };   // E21
            // ---- 2Nxx pins -> BR1 (branch 0) --------------------------------
            6'd40: mux_code = {2'd0, 4'd3 };   // H20
            6'd41: mux_code = {2'd0, 4'd2 };   // H19
            6'd42: mux_code = {2'd0, 4'd15};   // G20
            6'd43: mux_code = {2'd0, 4'd14};   // G19
            6'd44: mux_code = {2'd0, 4'd1 };   // H18
            6'd45: mux_code = {2'd0, 4'd0 };   // H17
            6'd46: mux_code = {2'd0, 4'd13};   // G18
            6'd47: mux_code = {2'd0, 4'd12};   // G17
            default: mux_code = 6'd0;          // unreachable, see above
            endcase
        end
    endfunction

    //==========================================================================
    // Chain word for the selected element (sec 6).
    //   branch / channel come from the aperture table above, NOT from
    //   elem_sel[5:4] / elem_sel[3:0] - the wiring is not in array order.
    //   word_ROOT       = 1 << ROOT_SW_BR[branch]   (SW5 / SW7 / SW11)
    //   word_BR[branch] = 1 << channel              the other two words are zero
    // Wire order is tail first - BR3, BR2, BR1, ROOT - MSB (SW15) first inside
    // each word.  Sending chain_word MSB first produces exactly that stream:
    // the first bit out travels furthest, so the LAST 16 bits sent (w_root)
    // stay in the device nearest the FPGA, which is the root mux.
    //==========================================================================
    wire golay = cfg_method == 2'd1;
    wire neighbor = cfg_method == 2'd2;
    wire multi_rx = cfg_method == 2'd3;
    // Slot 0 = self, 1 = left, 2 = right. Skip nonexistent edge receivers.
    reg [1:0] rx_slot = 0;
    reg member_b = 0;
    reg switching_rx = 0;
    assign shot_kind = multi_rx ? rx_slot : golay ? (member_b ? 2'd2 : 2'd1) :
                       neighbor ? 2'd3 : 2'd0;
    wire change_rx = neighbor || (multi_rx && rx_slot != 0);
    wire [5:0] rx_element = neighbor ? (element_current ^ 6'd1) :
                            rx_slot == 1 ? element_current - 1'b1 : element_current + 1'b1;
    wire [5:0] switch_element = (change_rx && state == S_INHIBIT) ? rx_element : elem_sel;
    wire last_tx_shot = (!golay || member_b) &&
                        (!multi_rx || rx_slot == 2 || (elem_sel == N_ELEM-1 && rx_slot == 1));
    wire [5:0]  elem_hw   = mux_code(switch_element);
    wire [1:0]  branch    = elem_hw[5:4];
    wire [3:0]  channel   = elem_hw[3:0];
    wire [15:0] onehot_ch = 16'h0001 << channel;

    localparam [15:0] ROOT_B0   = 16'h0001 << ROOT_SW_BR0;
    localparam [15:0] ROOT_B1   = 16'h0001 << ROOT_SW_BR1;
    localparam [15:0] ROOT_B2   = 16'h0001 << ROOT_SW_BR2;
    localparam [15:0] ROOT_MASK = ROOT_B0 | ROOT_B1 | ROOT_B2;

    wire [15:0] w_root = (branch == 2'd0) ? ROOT_B0 :
                         (branch == 2'd1) ? ROOT_B1 :
                         (branch == 2'd2) ? ROOT_B2 : 16'h0000;
    wire [15:0] w_br1  = (branch == 2'd0) ? onehot_ch : 16'h0000;
    wire [15:0] w_br2  = (branch == 2'd1) ? onehot_ch : 16'h0000;
    wire [15:0] w_br3  = (branch == 2'd2) ? onehot_ch : 16'h0000;

    wire [63:0] walk_word = {w_br3, w_br2, w_br1, w_root};

    //--------------------------------------------------------------------------
    // Static-mux bench word: one root switch and one leaf switch, constant for
    // every element of every frame.  Built at elaboration so it is a literal in
    // the netlist and cannot be perturbed by the element list or the host.
    //--------------------------------------------------------------------------
    localparam [15:0] STATIC_ROOT_W = 16'h0001 << MUX_STATIC_ROOT;
    localparam [15:0] STATIC_LEAF_W = 16'h0001 << MUX_STATIC_CH;
    localparam [63:0] STATIC_WORD   =
        {(MUX_STATIC_BR == 2) ? STATIC_LEAF_W : 16'h0000,   // BR3, sent first
         (MUX_STATIC_BR == 1) ? STATIC_LEAF_W : 16'h0000,   // BR2
         (MUX_STATIC_BR == 0) ? STATIC_LEAF_W : 16'h0000,   // BR1
         STATIC_ROOT_W};                                    // ROOT, sent last

    wire [63:0] chain_word = (MUX_STATIC != 0) ? STATIC_WORD : walk_word;

    // Invariants.  Two closed ROOT channels short two branch buses together;
    // two closed branch channels put two elements in parallel across the
    // pulser.  Both are damaging, so check before the word can reach a latch.
    // In static mode the word is a one-hot-per-device constant by construction,
    // and the element index no longer selects anything, so the check is moot.
    wire [15:0] w_br_all  = w_br1 | w_br2 | w_br3;
    wire [2:0]  br_nz     = {(w_br3 != 16'h0), (w_br2 != 16'h0), (w_br1 != 16'h0)};
    wire        root_1hot = (w_root  != 16'h0) && ((w_root  & (w_root  - 16'h1)) == 16'h0);
    wire        br_1hot   = (w_br_all != 16'h0) && ((w_br_all & (w_br_all - 16'h1)) == 16'h0);
    wire        root_rng  = ((w_root & ~ROOT_MASK) == 16'h0); // SW5/SW7/SW11 only
    wire        br_single = (br_nz == 3'b001) || (br_nz == 3'b010) || (br_nz == 3'b100);
    wire        br_match  = (branch == 2'd0) ? (w_br1 != 16'h0) :
                            (branch == 2'd1) ? (w_br2 != 16'h0) :
                            (branch == 2'd2) ? (w_br3 != 16'h0) : 1'b0;
    wire        word_ok   = (MUX_STATIC != 0) ? 1'b1 :
                            (root_1hot && root_rng && br_1hot && br_single &&
                             br_match  && (switch_element < N_ELEM));

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
    reg [5:0]  prev_elem  = 6'd0;    // ...and the element that word selected
    reg        seen_first = 1'b0;    // one shift has completed since reset
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
    //
    // The engine counts HALF cycles.  A fixed burst is 2*n_cycles halves all
    // t_drive wide; a chirp is cfg_chirp_len halves whose widths walk the
    // table.  half_idx is reset while the settle timer runs, so the async
    // table read (half_drive) is valid long before the first load, and it is
    // pre-incremented on each load so the NEXT width is settling on the read
    // port for the whole of the current driven phase and dead gap.
    //==========================================================================
    wire [15:0] t_dead_eff  = (cfg_t_dead < T_DEAD_FL) ? T_DEAD_FL : cfg_t_dead;
    wire [15:0] t_drive_eff = (cfg_t_drive == 16'd0) ? 16'd1 : cfg_t_drive;
    wire [7:0]  n_cyc_eff   = (cfg_n_cycles == 8'd0) ? 8'd1 : cfg_n_cycles;

    wire        chirp_en    = !golay && (cfg_chirp_len != 8'd0);
    reg  [7:0]  half_idx    = 8'd0;     // table entry for the NEXT driven phase
    wire [15:0] chirp_q     = chirp_ram[half_idx];
    wire [15:0] chirp_cur   = (chirp_q == 16'd0) ? 16'd1 : chirp_q;
    wire [15:0] half_drive  = chirp_en ? chirp_cur : t_drive_eff;
    wire [8:0]  total_half  = golay ? 9'd8 : chirp_en ? {1'b0, cfg_chirp_len}
                                       : {n_cyc_eff, 1'b0};   // 2 * n_cycles

    // Each chip is a full bipolar cycle. A = +++-, B = ++-+.
    wire invert_chip = golay && (half_idx[2:1] == (member_b ? 2'd2 : 2'd3));
    wire next_negative = half_idx[0] ^ invert_chip;

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
    // ADC sample-grid tick.  The AFE free-runs against this clock, so a burst
    // launched on settle expiry alone lands anywhere on the 40 MSPS grid and
    // the receive window opens with a uniform 0-50 ns error - RANDOM PHASE per
    // element across the aperture at the beamformer, which is exactly the
    // per-element jitter the host has been fighting.  Holding the first HV
    // edge for the next grid tick pins burst-to-grid at a constant offset;
    // what remains is the ~10 ns quantisation of this synchroniser, and a
    // constant is calibration (t0), not jitter.
    //==========================================================================
    (* ASYNC_REG = "TRUE" *) reg [1:0] adc_ts = 2'b00;
    reg adc_ts_d = 1'b0;
    always @(posedge clk) begin
        adc_ts   <= {adc_ts[0], adc_sync_tog};
        adc_ts_d <= adc_ts[1];
    end
    wire adc_tick = adc_ts[1] ^ adc_ts_d;

    //==========================================================================
    // Sequencer
    //==========================================================================
    reg [23:0] tmr           = T_CLR_C - 1; // general state timer (CLR out of POR)
    reg [5:0]  grid_wait     = 6'd0;    // cycles spent holding for adc_tick
    reg        gridded       = 1'b0;    // grid tick seen; tmr now counts the trim
    reg [15:0] btmr          = 16'd0;   // burst phase timer
    reg [8:0]  half_rem      = 9'd0;    // driven half cycles still to fire
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
        else if ((state == S_READY) && arm && !fault_r && capture_ready && (list_ptr == 6'd0)) start_pend <= 1'b0;
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
            // word_ok_pend describes the word being shifted in, so it is live
            // from the shift until S_LATCH moves the switches - S_SHIFT and
            // S_TCS.  It is NOT checked in S_WAITRX any more: that state now
            // runs BEFORE the shift, where the register still holds the
            // element that already fired and was already checked.
            end else if (!word_ok_pend &&
                         ((state == S_SHIFT) || (state == S_TCS))) begin
                trip = 1'b1;  trip_code = FC_ELEMENT;
            end else if ((CHAIN_CHECK != 0) && shift_done && !chain_match &&
                         seen_first &&
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
        // S_INHIBIT and S_WAITRX.  Nothing touches the chain while it is
        // non-zero; the next shift is issued when it hits zero.
        if (rx_tmr != 24'd0) rx_tmr <= rx_tmr - 24'd1;

        if (rst) begin
            rx_slot <= 0;
            member_b <= 0;
            switching_rx <= 0;
            state           <= S_RST;
            tmr             <= T_CLR_C - 1;
            grid_wait       <= 6'd0;
            gridded         <= 1'b0;
            clr_r           <= 1'b1;
            le_r            <= 1'b1;
            ina_r           <= 1'b0;
            inb_r           <= 1'b1;
            oe_r            <= 1'b0;
            rx_tmr          <= 24'd0;
            btmr            <= 16'd0;
            half_rem        <= 9'd0;
            half_idx        <= 8'd0;
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
            rx_slot <= 0;
            member_b <= 0;
            switching_rx <= 0;
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
                if ((continuous || start_pend) && (list_ptr == 6'd0) && capture_ready) begin
                    shift_data    <= chain_word;
                    shift_start   <= 1'b1;
                    elem_pend     <= elem_sel;
                    word_ok_pend  <= word_ok;
                    last_of_frame <= (list_len == 7'd1) && last_tx_shot;
                    run           <= 1'b1;
                    state         <= S_SHIFT;
                end
            end

            //------------------------------------------------------------------
            // 64 chain bits.  LE stays high the whole time.  The previous
            // element's receive window has already closed (S_WAITRX waited it
            // out before issuing this shift), so nothing is listening.
            //------------------------------------------------------------------
            S_SHIFT: if (shift_done) begin
                if (!switching_rx && last_tx_shot)
                    list_ptr <= list_last ? 6'd0 : (list_ptr + 6'd1);
                tmr      <= T_CS_C - 1;
                state    <= S_TCS;
            end

            //------------------------------------------------------------------
            // The rest of the receive window, after S_INHIBIT.  This is the
            // quiet interval: the chain is idle - clk low, din low, LE high -
            // and stays that way until rx_tmr expires.  Only then is the next
            // element's word shifted in.
            //
            // list_ptr was advanced at the end of the last S_SHIFT, so
            // chain_word / elem_sel already describe the NEXT element and have
            // had the whole receive window to settle through the distributed
            // RAM and mux_code().
            //------------------------------------------------------------------
            // Host/FIFO stalls may extend the actual capture beyond rx_tmr.
            // Hold the current switch selection and keep SPI quiet until the
            // receiver has drained and completed its configured DAC gap.
            S_WAITRX: if ((rx_tmr == 24'd0) && capture_ready) begin
                if (!run) begin
                    state <= S_READY;                // frame finished, draining done
                end else begin
                    shift_data    <= chain_word;
                    shift_start   <= 1'b1;
                    elem_pend     <= elem_sel;
                    word_ok_pend  <= word_ok;
                    last_of_frame <= list_last && last_tx_shot;
                    state         <= S_SHIFT;
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
                         if (!switching_rx) element_current <= elem_pend;
                         half_idx        <= 8'd0;    // table read settles in S_SETTLE
                         tmr             <= t_settle_eff - 24'd1;
                         gridded         <= 1'b0;    // S_SETTLE's only entry, so
                         state           <= S_SETTLE; // clearing here covers every
                                                     // disarm/trip exit path too
                     end

            //------------------------------------------------------------------
            // t_ON / t_OFF.  The analog node must be quiet at ground for this
            // entire interval - nothing else may happen here.
            //
            // After the timer, hold for the next ADC grid tick so the CAPTURE
            // WINDOW lands at a fixed phase of the sample grid (see adc_tick
            // above).  Ticks arrive every 200 ns; the 63-cycle (630 ns) bound
            // covers three tick periods, so a dead AFE stream degrades to the
            // old unaligned launch instead of hanging the sequencer - the
            // pulser must keep firing with no ADC just as it does with no
            // host.  The hold only ever LENGTHENS the settle, so the datasheet
            // floor T_SETTLE_MIN is untouched.
            //
            // tx_sync is issued AT the tick and the HV edge is then held off a
            // further trim_sel cycles (see the trim table above).  That split
            // is the whole point: the gate is slaved to tx_sync and re-quantises
            // to a 50 ns ADC word boundary, so it must stay on the grid, while
            // the pulse is free to move against it in 10 ns steps.  gridded
            // marks the changeover - before it, tmr is the settle wait; after
            // it, tmr is the trim.  Both live in S_SETTLE because that is what
            // the trim physically IS: more settle before the shot.  Worst case
            // adds 41 us to a state the watchdog gives 200 ms.
            //------------------------------------------------------------------
            S_SETTLE: if (switching_rx) begin
                          if (tmr != 0) tmr <= tmr - 1'b1;
                          else begin
                              switching_rx <= 0;
                              state <= S_WAITRX;
                          end
                      end else if (!gridded) begin
                          if (tmr != 24'd0) begin
                              tmr       <= tmr - 24'd1;
                              grid_wait <= 6'd0;
                          end else if (!capture_ready) begin
                              // Recheck immediately before reserving a shot.
                              // Waiting must not consume the sample-grid timeout.
                              grid_wait <= 6'd0;
                          end else if (!adc_tick && (grid_wait != 6'd63)) begin
                              grid_wait <= grid_wait + 6'd1;
                          end else begin
                              tx_sync <= 1'b1;       // the gate opens from here
                              gridded <= 1'b1;
                              tmr     <= {12'd0, trim_sel};
                          end
                      end else if (tmr != 24'd0) begin
                          tmr <= tmr - 24'd1;
                      end else begin
                          half_rem <= total_half - 9'd1;
                          half_idx <= 8'd1;          // prefetch the next width
                          btmr     <= half_drive - 16'd1;
                          ina_r    <= 1'b1;          // ina 0->1 only: idle -> +HV
                          gridded  <= 1'b0;
                          state    <= S_FIRE_P;
                      end

            //------------------------------------------------------------------
            // Burst.  Exactly one of ina / inb changes at every transition.
            // Each driven phase takes its width from half_drive - the table
            // entry in chirp mode, t_drive otherwise - and every dead gap is
            // t_dead.  Both dead states test half_rem, so a chirp of odd
            // length ends after a +HV phase and an even one after -HV; either
            // way the burst is parked in the idle state when it leaves.
            //------------------------------------------------------------------
            S_FIRE_P: if (btmr != 16'd0) btmr <= btmr - 16'd1;
                      else begin
                          ina_r <= 1'b0;             // +HV -> idle
                          btmr  <= t_dead_eff - 16'd1;
                          state <= S_DEAD_A;
                      end

            S_FIRE_N: if (btmr != 16'd0) btmr <= btmr - 16'd1;
                      else begin
                          inb_r <= 1'b1;             // -HV -> idle
                          btmr  <= t_dead_eff - 16'd1;
                          state <= S_DEAD_B;
                      end

            S_DEAD_A, S_DEAD_B: if (btmr != 16'd0) begin
                          btmr <= btmr - 16'd1;
                      end else if (half_rem != 9'd0) begin
                          half_rem <= half_rem - 9'd1;
                          half_idx <= half_idx + 8'd1;
                          ina_r    <= !next_negative;
                          inb_r    <= !next_negative;
                          btmr     <= half_drive - 16'd1;
                          state    <= next_negative ? S_FIRE_N : S_FIRE_P;
                      end else begin
                          // burst complete, parked in the idle state
                          rx_tmr <= rx_win;
                          tmr    <= t_inhibit_eff - 24'd1;
                          state  <= S_INHIBIT;
                      end

            //------------------------------------------------------------------
            // MAX14866 transmit detector: SPI writes in this window are
            // silently discarded.  No chain activity until it expires.
            //
            // This runs concurrently with the head of the receive window
            // (rx_tmr started at the same edge), and the shift that follows it
            // now waits for the WHOLE window in S_WAITRX, so t_inhibit is
            // hidden under the RX window for any sane t_ring + t_rx and costs
            // nothing.  It is still counted separately rather than assumed:
            // a host is free to set a receive window shorter than 4.5 us, and
            // the t_inhibit failure mode is silent.
            //------------------------------------------------------------------
            S_INHIBIT: if (tmr != 24'd0) begin
                tmr <= tmr - 24'd1;
            end else begin
                if (golay) member_b <= !member_b;
                if (last_of_frame) frame_count <= frame_count + 16'd1;
                // drain the RX window either way; S_WAITRX issues the next
                // shift, or parks in S_READY when the frame is done.
                if (last_of_frame && !continuous) run <= 1'b0;
                if (multi_rx) begin
                    if (rx_slot == 0) rx_slot <= element_current == 0 ? 2 : 1;
                    else if (rx_slot == 1 && element_current != N_ELEM-1) rx_slot <= 2;
                    else rx_slot <= 0;
                end
                if (change_rx) begin
                    switching_rx <= 1;
                    shift_data <= chain_word;
                    word_ok_pend <= word_ok;
                    shift_start <= 1;
                    state <= S_SHIFT;
                end else state <= S_WAITRX;
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
    // Chain loopback check.
    //
    // rx_sr holds what came back out of the tail of the daisy chain during THIS
    // shift, which is the word sent during the PREVIOUS shift - the chain is 64
    // flops deep, so DOUT lags DIN by exactly one word.  chain_match is that
    // comparison; all this block does is record the failures.
    //
    // Because the readback is one word behind, a mismatch reported at shift N
    // condemns the word sent at shift N-1.  That is prev_elem, NOT the element
    // being shifted now - get this backwards and the error is blamed on the
    // wrong element, which is the whole point of the measurement.
    //
    // The first compare after reset is recorded in chain_ok (so the power-up
    // liveness check the shifter comment describes is still observable) but is
    // NOT counted here.  S_SELFT shifts 64 zeros while prev_word is still zero,
    // so that compare only means anything if the MAX14866 shift registers come
    // out of POR zeroed.  If they do, discarding it costs nothing; if they do
    // not, counting it would leave the indicator permanently lit and useless.
    //
    // A mismatch means the 64-bit word did not survive in the chain.  The
    // classic cause is the MAX14866 transmit detector still inhibiting SPI when
    // the shift starts: it swallows leading clocks, the word arrives rotated,
    // and a different switch closes than the element id in the frame header
    // claims.  That is now much harder to hit - the shift waits out t_inhibit
    // AND the whole receive window - so a rotation appearing here points at the
    // chain itself (signal integrity on CLK/DIN, a marginal device) rather than
    // at the timing.  chain_err_word is kept so the rotation can be read
    // directly: compare it against the expected one-hot-per-device pattern and
    // the number of eaten clocks falls out.
    //==========================================================================
    always @(posedge clk) begin
        chain_err_stb <= 1'b0;

        if (rst) begin
            prev_elem      <= 6'd0;
            seen_first     <= 1'b0;
            chain_err_cnt  <= 16'd0;
            chain_err_elem <= 6'd0;
            chain_err_word <= 64'h0;
        end else if (shift_done) begin
            prev_elem <= elem_pend;          // in lockstep with prev_word

            if (!seen_first) begin
                seen_first <= 1'b1;
            end else if (!chain_match) begin
                chain_err_elem <= prev_elem;
                chain_err_word <= rx_sr;
                chain_err_stb  <= 1'b1;
                if (chain_err_cnt != 16'hFFFF)
                    chain_err_cnt <= chain_err_cnt + 16'd1;
            end
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
