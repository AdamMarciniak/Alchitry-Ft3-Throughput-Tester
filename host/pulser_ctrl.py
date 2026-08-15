# pulser_ctrl.py - transmit sequencer control over the FT601 control pipe.
#
# Usable two ways.
#
# 1. As a library, from any host app that already has send_cmd()/cmd():
#
#        from pulser_ctrl import PulserCtl, build_pulser_panel
#        pulser = PulserCtl(send_cmd, cmd)
#        build_pulser_panel(frame, pulser, FG=FG, BG=BG, GRID=GRID)   # optional
#        pulser.push_all()        # make the FPGA agree with the UI
#
#    This is how scope_host.py uses it.
#
# 2. As a standalone CLI, for bench tweaks with no GUI:
#
#        python pulser_ctrl.py --stop
#        python pulser_ctrl.py --start --pulses 3 --width 80 --dead 40
#        python pulser_ctrl.py --single 19
#        python pulser_ctrl.py --chirp 2 4 20  (2->4 MHz linear chirp over 20 us)
#        python pulser_ctrl.py --chirp-off     (back to the fixed burst)
#        python pulser_ctrl.py --show          (print settings, send nothing)
#
#    The FT601 opens exclusively, so close scope_host.py first.
#
# The sequencer free-runs on its own timebase and is NOT gated by START/STOP -
# it keeps firing whether or not the ADC stream is running, and nothing here
# touches the receive path.
#
# There is no readback: the FPGA never reports its state, so what this module
# prints is what it has SENT, not what the hardware confirms.  Settings persist
# in the FPGA until the next command or a reset.

import sys, time

CLK_HZ       = 100_000_000          # FPGA clk_in
NS_PER_CYCLE = 1e9 / CLK_HZ         # 10.0 ns

# --- opcodes (must match ctrl_decode.v) ---------------------------------------
OP_PLS_ARM     = 0x10   # payload[0]: 1 = run, 0 = stop + park driver + CLR muxes
OP_PLS_NCYC    = 0x11   # payload[7:0]:  +/- pulse pairs per burst
OP_PLS_TDRIVE  = 0x12   # payload[15:0]: width of each +HV / -HV pulse, cycles
OP_PLS_TDEAD   = 0x13   # payload[15:0]: gap between opposite polarities, cycles
OP_PLS_TSETTLE = 0x14   # payload: LE rise -> first HV edge, cycles
OP_PLS_TINHIB  = 0x15   # payload: last HV edge -> chain clocking, cycles
OP_PLS_TRING   = 0x16   # payload: ringdown blanking, cycles
OP_PLS_TRX     = 0x17   # payload: echo receive window, cycles
OP_PLS_NELEM   = 0x18   # payload[6:0]: elements per frame
OP_PLS_ELEM    = 0x19   # payload: {addr[5:0], data[5:0]} element-list write
OP_PLS_FCLR    = 0x1A   # clear a latched pulser fault
OP_PLS_CHIRP   = 0x1B   # payload: {addr[7:0], drive[15:0]} chirp-table write
OP_PLS_CLEN    = 0x1C   # payload[7:0]: chirp half cycles, 0 = fixed burst

# --- datasheet floors, enforced in RTL too -------------------------------------
# The FPGA clamps these regardless of what we send; they are repeated here so
# the UI can show the limit rather than silently disagreeing with the hardware.
#   T_SETTLE   MAX14866 t_ON / t_OFF, 4 us max
#   T_INHIBIT  MAX14866 SPI lockout after HV, 4.5 us - going below this makes
#              chain writes vanish with NO error and fires the wrong element
T_SETTLE_MIN_US  = 4.0
T_INHIBIT_MIN_US = 4.5
# TC6320 turn-off is t_d(OFF) 20 ns + t_f 15 ns = 35 ns worst case.  Below this
# both FETs can conduct at once.  NOT clamped in RTL - the combinational
# interlock catches the static case, but a short dead time is still a real
# shoot-through risk once HV is connected.
T_DEAD_MIN_NS = 40.0

N_ELEM_MAX = 48

# MAX14866 chain shift, must match SPI_HALF / CHAIN_BITS in tx_sequencer.v.
# 64 bits at one bit per 2*SPI_HALF cycles = 640 cycles = 6.4 us.  This used to
# be free: the shift ran inside the receive window, early on where the echo is
# ringdown anyway.  It is now serialised AFTER the window so that no chain edge
# lands while an element is connected to the receive path, so it shows up in the
# element period - see element_period_us().
CHAIN_BITS   = 64
SPI_HALF_CYC = 5
T_SHIFT_US   = CHAIN_BITS * 2 * SPI_HALF_CYC * 1e6 / CLK_HZ

# Chirp table geometry, must match tx_sequencer.v.  One table entry is the
# driven width of one HALF cycle (one +HV or -HV phase); the dead gap after
# each phase is t_dead as usual, so the half PERIOD the transducer sees is
# entry + dead.  255 halves at ~3 MHz is ~42 us of sweep - plenty.
CHIRP_DEPTH   = 256
CHIRP_LEN_MAX = 255

DEFAULTS = dict(
    arm         = True,
    n_cycles    = 2,        # 2 positive + 2 negative pulses
    t_drive_ns  = 100.0,    # width of each pulse
    t_dead_ns   = 40.0,     # gap between + and -
    t_settle_us = 5.0,      # LE -> fire
    t_inhib_us  = 4.5,      # last pulse -> SPI mux clocking
    t_ring_us   = 3.0,      # ringdown blanking
    t_rx_us     = 130.0,    # receive window (~100 mm at 1540 m/s)
    n_elem      = 48,       # elements per frame
    chirp_on    = False,    # coded excitation off: plain n_cycles burst
    chirp_f0_mhz = 2.0,     # sweep start (first half cycle)
    chirp_f1_mhz = 4.0,     # sweep end (last half cycle)
    chirp_us    = 20.0,     # sweep duration
)


def ns_to_cyc(ns):  return max(1, int(round(float(ns) / NS_PER_CYCLE)))
def us_to_cyc(us):  return max(1, int(round(float(us) * CLK_HZ / 1e6)))
def cyc_to_ns(c):   return c * NS_PER_CYCLE
def cyc_to_us(c):   return c * 1e6 / CLK_HZ


# =============================================================================
# Chirp design
# =============================================================================
# The pulser is a switched bipolar bridge: +HV, ground, or -HV, no amplitude
# control.  A chirp on such a transmitter is a frequency-swept SQUARE wave -
# each half cycle is one driven phase and the sweep lives entirely in how the
# half-cycle boundaries are spaced.  The transducer's own band does the
# smoothing; what matters here is that the SWITCHING TIMES track the ideal
# chirp phase, so the design works on cumulative phase:
#
#   linear FM      f(t) = f0 + (f1 - f0) * t / T
#   phase (cycles) p(t) = f0*t + (f1-f0)/(2T) * t^2
#
# and a half-cycle boundary sits wherever p(t) crosses a multiple of 1/2.
# Those boundary TIMES are quantised to the 10 ns FPGA clock and the table
# entries are their DIFFERENCES (minus the dead gap), so the rounding error
# never accumulates: every edge is within 5 ns of the ideal chirp, however
# long the sweep is.  Quantising the half-periods instead would random-walk
# the phase by sqrt(M) * 5 ns, which by the end of a long sweep is a
# significant fraction of a cycle - the compressed pulse pays for that
# directly, so it is the differences of rounded times, not rounded
# differences.
def chirp_edges_cyc(f0_hz, f1_hz, dur_s):
    """Half-cycle boundary times of an f0 -> f1 linear chirp, in clk cycles.

    Returns a list of M+1 strictly increasing integers: edge m is where driven
    phase m starts, edge M is where the burst ends.  M = round((f0+f1)*T), the
    whole number of half cycles closest to the requested duration, capped at
    CHIRP_LEN_MAX."""
    f0, f1, T = float(f0_hz), float(f1_hz), float(dur_s)
    if f0 <= 0 or f1 <= 0 or T <= 0:
        raise ValueError("chirp needs positive f0, f1 and duration")
    M = int(round((f0 + f1) * T))               # 2 * (mean f) * T half cycles
    M = max(1, min(CHIRP_LEN_MAX, M))
    k = (f1 - f0) / T
    edges = []
    for m in range(M + 1):
        if abs(k) < 1e-3:                       # constant frequency: k -> 0 limit
            t = m / (2.0 * f0)
        else:                                   # solve f0*t + k*t^2/2 = m/2
            t = (-f0 + (f0 * f0 + k * m) ** 0.5) / k
        edges.append(int(round(t * CLK_HZ)))
    return edges


def chirp_table(f0_hz, f1_hz, dur_s, dead_cyc):
    """FPGA chirp-table entries: driven width per half cycle, clk cycles.

    The half PERIOD is edge-to-edge; the FPGA inserts dead_cyc of idle after
    every driven phase, so the driven width is the difference minus the dead
    gap.  Edges too close together for that (possible only at frequencies far
    above any transducer here) are pushed apart so every driven phase is at
    least one cycle - the same floor the RTL enforces."""
    edges = chirp_edges_cyc(f0_hz, f1_hz, dur_s)
    dead  = max(1, int(dead_cyc))
    tab, prev = [], edges[0]
    for e in edges[1:]:
        e = max(e, prev + dead + 1)             # driven phase >= 1 cycle
        tab.append(e - prev - dead)
        prev = e
    return tab


class PulserCtl:
    """Holds the current pulser settings and pushes them to the FPGA."""

    def __init__(self, send_cmd, cmd):
        self._send = send_cmd
        self._cmd  = cmd
        self.__dict__.update(DEFAULTS)
        self.single_elem = None      # None = walk 0..n_elem-1
        # Bumped whenever a setting that changes the TRANSMIT WAVEFORM is sent
        # (burst shape or chirp).  A receive-side matched filter caches its
        # reference against this, so it rebuilds exactly when the pulse moves.
        self.tx_gen = 0

    # -- derived ---------------------------------------------------------------
    def _chirp_edges(self):
        return chirp_edges_cyc(self.chirp_f0_mhz * 1e6, self.chirp_f1_mhz * 1e6,
                               self.chirp_us * 1e-6)

    def f0_hz(self):
        """Centre frequency: one cycle is drive/dead/drive/dead; a chirp
        reports the middle of its sweep."""
        if self.chirp_on:
            return 0.5 * (self.chirp_f0_mhz + self.chirp_f1_mhz) * 1e6
        period_ns = 2.0 * (cyc_to_ns(ns_to_cyc(self.t_drive_ns)) +
                           cyc_to_ns(ns_to_cyc(self.t_dead_ns)))
        return 1e9 / period_ns if period_ns > 0 else 0.0

    def burst_ns(self):
        if self.chirp_on:
            return cyc_to_ns(self._chirp_edges()[-1])
        return self.n_cycles * 2.0 * (cyc_to_ns(ns_to_cyc(self.t_drive_ns)) +
                                      cyc_to_ns(ns_to_cyc(self.t_dead_ns)))

    def element_period_us(self):
        """LE fall to LE fall, matching the FSM's state sequence.

        burst -> S_INHIBIT / S_WAITRX -> S_SHIFT -> t_CS -> LE low -> t_settle.

        t_inhibit runs concurrently with the receive window (both start at the
        end of the burst), so the dead interval is the LONGER of the two, not
        the sum - it only shows up at all if the window is set shorter than the
        4.5 us lockout.  The chain shift is NOT concurrent any more: it waits
        for the window to close so the receive period stays electrically quiet,
        which is why T_SHIFT_US is a term here.
        """
        settle = max(self.t_settle_us, T_SETTLE_MIN_US)
        inhib  = max(self.t_inhib_us, T_INHIBIT_MIN_US)
        quiet  = max(self.t_ring_us + self.t_rx_us, inhib)
        return (0.02 + 0.05 + settle + self.burst_ns() / 1e3 +
                quiet + T_SHIFT_US)

    def frame_ms(self):
        n = 1 if self.single_elem is not None else self.n_elem
        return n * self.element_period_us() / 1e3

    # -- setters (each sends one command) --------------------------------------
    def set_arm(self, on):
        self.arm = bool(on)
        self._send(self._cmd(OP_PLS_ARM, 1 if self.arm else 0), "pls_arm")

    def set_n_cycles(self, n):
        self.n_cycles = max(1, min(255, int(n)))
        self.tx_gen += 1
        self._send(self._cmd(OP_PLS_NCYC, self.n_cycles), "pls_ncyc")

    def set_t_drive_ns(self, ns):
        self.t_drive_ns = float(ns)
        self.tx_gen += 1
        self._send(self._cmd(OP_PLS_TDRIVE, ns_to_cyc(ns)), "pls_tdrive")

    def set_t_dead_ns(self, ns):
        self.t_dead_ns = float(ns)
        self.tx_gen += 1
        self._send(self._cmd(OP_PLS_TDEAD, ns_to_cyc(ns)), "pls_tdead")
        # The chirp table stores DRIVEN widths; the half period the transducer
        # sees is width + dead.  A new dead time therefore changes every half
        # period unless the table is rebuilt around it.
        if self.chirp_on:
            self._upload_chirp()

    def set_t_settle_us(self, us):
        self.t_settle_us = float(us)
        self._send(self._cmd(OP_PLS_TSETTLE, us_to_cyc(us)), "pls_tsettle")

    def set_t_inhib_us(self, us):
        self.t_inhib_us = float(us)
        self._send(self._cmd(OP_PLS_TINHIB, us_to_cyc(us)), "pls_tinhib")

    def set_t_ring_us(self, us):
        self.t_ring_us = float(us)
        self._send(self._cmd(OP_PLS_TRING, us_to_cyc(us)), "pls_tring")

    def set_t_rx_us(self, us):
        self.t_rx_us = float(us)
        self._send(self._cmd(OP_PLS_TRX, us_to_cyc(us)), "pls_trx")

    def set_n_elem(self, n):
        self.n_elem = max(1, min(N_ELEM_MAX, int(n)))
        if self.single_elem is None:
            self._send(self._cmd(OP_PLS_NELEM, self.n_elem), "pls_nelem")

    def set_single_elem(self, elem):
        """elem=None walks the whole aperture; an int fires only that element.

        Single-element mode writes the index into slot 0 of the element list
        and sets the list length to 1, so the sequencer repeats one element.
        """
        self.single_elem = None if elem is None else max(0, min(N_ELEM_MAX - 1, int(elem)))
        if self.single_elem is None:
            self._send(self._cmd(OP_PLS_ELEM, (0 << 6) | 0), "pls_elem")
            self._send(self._cmd(OP_PLS_NELEM, self.n_elem), "pls_nelem")
        else:
            self._send(self._cmd(OP_PLS_ELEM, (0 << 6) | self.single_elem), "pls_elem")
            self._send(self._cmd(OP_PLS_NELEM, 1), "pls_nelem")

    def clear_fault(self):
        self._send(self._cmd(OP_PLS_FCLR), "pls_fclr")

    def write_element(self, slot, elem):
        """Raw element-list write: slot 0..63 <- element index 0..47."""
        self._send(self._cmd(OP_PLS_ELEM, ((slot & 0x3F) << 6) | (elem & 0x3F)),
                   "pls_elem")

    # -- chirp -----------------------------------------------------------------
    def chirp_table_now(self):
        """The table the current settings would (or did) load, driven widths in
        clk cycles - one entry per half cycle."""
        return chirp_table(self.chirp_f0_mhz * 1e6, self.chirp_f1_mhz * 1e6,
                           self.chirp_us * 1e-6, ns_to_cyc(self.t_dead_ns))

    def _upload_chirp(self):
        """Write the whole table, then the length - the length is what arms it,
        so a partially loaded table can never fire."""
        tab = self.chirp_table_now()
        for i, w in enumerate(tab):
            self._send(self._cmd(OP_PLS_CHIRP, (i << 16) | (w & 0xFFFF)),
                       "pls_chirp")
        self._send(self._cmd(OP_PLS_CLEN, len(tab)), "pls_clen")
        self.tx_gen += 1

    def set_chirp_on(self, on):
        self.chirp_on = bool(on)
        if self.chirp_on:
            self._upload_chirp()
        else:
            self._send(self._cmd(OP_PLS_CLEN, 0), "pls_clen")
            self.tx_gen += 1

    def set_chirp_f0_mhz(self, mhz):
        self.chirp_f0_mhz = max(0.1, float(mhz))
        if self.chirp_on: self._upload_chirp()

    def set_chirp_f1_mhz(self, mhz):
        self.chirp_f1_mhz = max(0.1, float(mhz))
        if self.chirp_on: self._upload_chirp()

    def set_chirp_us(self, us):
        self.chirp_us = max(0.5, float(us))
        if self.chirp_on: self._upload_chirp()

    def tx_waveform(self, fs_hz):
        """The commanded transmit waveform as +/-1/0 samples at fs_hz - chirp
        or fixed burst, whichever is active, from the same quantised edge
        times the FPGA fires.  This is the matched-filter reference: what the
        transducer makes of it differs (its band, plus the RTZ dead gaps), but
        the switching times are exact, and those carry the code."""
        dead = ns_to_cyc(self.t_dead_ns)
        if self.chirp_on:
            edges = self._chirp_edges()
            halves = []
            prev = edges[0]
            for e in edges[1:]:
                e = max(e, prev + dead + 1)
                halves.append((prev, e - dead))
                prev = e
        else:
            drive, halves, t = ns_to_cyc(self.t_drive_ns), [], 0
            for _ in range(2 * self.n_cycles):
                halves.append((t, t + drive))
                t += drive + dead
        n = int(round(halves[-1][1] * fs_hz / CLK_HZ)) + 1
        out = [0.0] * max(n, 1)
        for m, (a, b) in enumerate(halves):
            i0 = int(round(a * fs_hz / CLK_HZ))
            i1 = max(int(round(b * fs_hz / CLK_HZ)), i0 + 1)
            s  = 1.0 if (m & 1) == 0 else -1.0
            for i in range(i0, min(i1, len(out))):
                out[i] = s
        return out

    # -- bulk ------------------------------------------------------------------
    def push_all(self):
        """Send every setting so the FPGA matches this object after a restart."""
        self.set_n_cycles(self.n_cycles)
        self.set_t_drive_ns(self.t_drive_ns)
        self.set_t_dead_ns(self.t_dead_ns)
        self.set_t_settle_us(self.t_settle_us)
        self.set_t_inhib_us(self.t_inhib_us)
        self.set_t_ring_us(self.t_ring_us)
        self.set_t_rx_us(self.t_rx_us)
        self.set_single_elem(self.single_elem)   # also sets the list length
        self.set_chirp_on(self.chirp_on)         # table + length, or length 0
        self.set_arm(self.arm)                   # arm last

    def summary(self):
        w = "elem %d only" % self.single_elem if self.single_elem is not None \
            else "elements 0-%d" % (self.n_elem - 1)
        if self.chirp_on:
            tab = self.chirp_table_now()
            tx = ("chirp %.2f->%.2f MHz  %d halves  burst %.1f us"
                  % (self.chirp_f0_mhz, self.chirp_f1_mhz, len(tab),
                     self.burst_ns() / 1e3))
        else:
            tx = ("%dx(%.0f ns +/- %.0f ns dead) -> f0 %.2f MHz  burst %.0f ns"
                  % (self.n_cycles,
                     cyc_to_ns(ns_to_cyc(self.t_drive_ns)),
                     cyc_to_ns(ns_to_cyc(self.t_dead_ns)),
                     self.f0_hz() / 1e6, self.burst_ns()))
        return ("pulser: %s  %s  settle %.1f us  inhibit %.1f us  "
                "rx %.0f us  %s  frame %.2f ms"
                % ("RUN" if self.arm else "STOPPED", tx,
                   self.t_settle_us, self.t_inhib_us, self.t_rx_us,
                   w, self.frame_ms()))


# =============================================================================
# Hover help
# =============================================================================
# One entry per control in the panel below, keyed by its label.  These describe
# what the FPGA actually does with the value, including the datasheet limits it
# is clamped to - a slider that silently disagrees with the hardware is worse
# than no slider.
HELP = {
"PULSER RUN":
    "Arms the transmit sequencer (tx_sequencer.v).\n\n"
    "OFF parks the MD1213 driver in its safe idle state (INA=0, INB=1), drops "
    "OE and asserts MUX_CLR, which opens every switch in the mux tree.\n\n"
    "The sequencer owns the timebase and comes up armed from power-on with no "
    "host present.\n\n"
    "In the SRC_SEQ apps (TFM, waterfall) the capture is SLAVED to it: each "
    "receive window starts a fixed pulse->rx delay after a real burst. So "
    "stopping the pulser also stops the ADC frames - no burst, no frame. The "
    "raw scope app (SRC_ADC) is unaffected and keeps streaming.",

"clr fault":
    "Clears a latched pulser fault.\n\n"
    "The FSM latches on shoot-through (INA high while INB low), a per-state "
    "watchdog timeout, or an element word that fails the one-hot check. It "
    "then sits in S_FAULT with MUX_CLR asserted and OE down until this is "
    "sent, or the board reset button is pressed. Nothing fires in the "
    "meantime.",

"pulses":
    "Number of +HV / -HV pulse PAIRS in each burst.\n\n"
    "N produces N positive and N negative pulses, always returning to the "
    "idle state between polarities and ending idle.\n\n"
    "More cycles put more energy into the transducer but narrow the "
    "bandwidth, which lengthens the pulse and costs axial resolution.",

"width ns":
    "Width of each +HV and each -HV pulse.\n\n"
    "Together with the dead time this sets the transmit centre frequency:\n"
    "    f0 = 1 / (2 x (width + dead))\n"
    "so 100 ns width + 40 ns dead gives ~3.57 MHz.\n\n"
    "Quantised to the 100 MHz FPGA clock, i.e. 10 ns steps. Match it to the "
    "transducer's resonance for the largest output.",

"dead ns":
    "Idle gap between opposite polarities, with both output FETs off.\n\n"
    "Must be longer than the TC6320 turn-off time - t_d(off) 20 ns + t_f "
    "15 ns = 35 ns worst case - or the high- and low-side devices can conduct "
    "at once. 40 ns is the practical floor.\n\n"
    "This is NOT clamped in the FPGA: the combinational interlock only catches "
    "the static case. It also forms part of f0 (see 'width ns').",

"settle us":
    "LE rising edge to the first HV edge - time allowed for the mux switches "
    "to finish moving.\n\n"
    "The MAX14866 specifies t_ON / t_OFF of 4 us max, and the datasheet "
    "requires the analog node to be quiet at ground for the entire settling "
    "time. Firing early stresses the part.\n\n"
    "The FPGA clamps this to 4.0 us minimum regardless of what is sent.",

"inhibit us":
    "Minimum time from the last HV edge to the next mux chain clocking.\n\n"
    "The MAX14866 has a transmit detector: any input above +/-2V inhibits SPI "
    "programming for up to 4.5 us. Chain writes inside that window are "
    "DISCARDED WITH NO ERROR - the shift register keeps its old contents and "
    "the next shot fires the previous element. The failure is completely "
    "silent, which is why the floor is enforced in RTL.\n\n"
    "It usually costs nothing: the sequencer holds the chain idle for the "
    "whole receive window anyway (ring + rx), so this only binds if that "
    "window is set shorter than 4.5 us.\n\n"
    "The FPGA clamps this to 4.5 us minimum.",

"ring us":
    "Ringdown blanking: dead time after the burst before the useful echo "
    "window starts.\n\n"
    "The transducer keeps ringing for some microseconds after transmit and "
    "that energy swamps near-field echoes. Raise it until the saturated "
    "leading edge of the trace is gone; every microsecond costs ~0.77 mm of "
    "near-field depth.",

"rx us":
    "Echo receive window per element, measured from the end of the ringdown "
    "blanking.\n\n"
    "At 1540 m/s the round trip means depth_mm is about 0.77 x rx_us, so "
    "130 us is roughly 100 mm.\n\n"
    "Longer windows see deeper but slow the frame rate proportionally, since "
    "every element in the frame pays it.",

"elements":
    "Elements fired per frame. The sequencer walks aperture positions 0 .. N-1 "
    "in order - left to right across the probe face - then repeats.\n\n"
    "Frame time = elements x element period, where the element period is "
    "settle + burst + ring + rx plus a little chain overhead.\n\n"
    "48 = the full aperture (3 leaf muxes x 16 channels).",

"single element":
    "Fire one element repeatedly instead of walking the aperture.\n\n"
    "Writes the chosen position into slot 0 of the element list and sets the "
    "list length to 1.",

"chirp":
    "Coded excitation: replace the fixed-frequency burst with a linear "
    "frequency sweep (chirp).\n\n"
    "The pulser can only switch +HV / 0 / -HV, so the chirp is a frequency-"
    "swept square wave: a table in the FPGA holds one driven width per half "
    "cycle and the sweep lives in how the switching edges are spaced. Edges "
    "are quantised to 10 ns against CUMULATIVE phase, so the timing error "
    "never accumulates across the sweep.\n\n"
    "A long sweep puts far more energy into the tissue than a 2-cycle burst "
    "at the same voltage (10*log10(T_chirp/T_burst) dB - a 20 us chirp vs a "
    "0.56 us burst is ~15 dB) while pulse compression on receive recovers "
    "the axial resolution of the full sweep BANDWIDTH. Turn on 'pulse comp' "
    "in the receive row when imaging with this, otherwise every echo is "
    "smeared over the whole sweep length.\n\n"
    "While ticked, the pulses/width sliders are ignored by the FPGA (the "
    "table drives the burst); dead ns still applies between every polarity "
    "flip and is folded into the designed half periods.",

"chirp f0 M":
    "Sweep START frequency, MHz - the frequency of the first half cycles.\n\n"
    "Keep the whole sweep inside the transducer's two-way band (CH6-2: "
    "roughly 2-6 MHz); energy outside it is spent heating the probe, and the "
    "compressed pulse only benefits from bandwidth the echo actually "
    "returns.\n\nf0 above f1 is a down-chirp, which is equally valid.",

"chirp f1 M":
    "Sweep END frequency, MHz - the frequency of the last half cycles.\n\n"
    "Axial resolution after compression is set by |f1 - f0|: c/(2B) is "
    "~0.4 mm at 2 MHz of sweep. Wider is sharper, until the transducer stops "
    "returning the edges of the band.",

"chirp us":
    "Sweep duration, microseconds.\n\n"
    "Longer = more transmitted energy (3 dB per doubling) and more gain from "
    "compression, but the burst occupies the near field for its whole "
    "length: nothing closer than c*T/2 (~15 mm at 20 us) can be separated "
    "from the transmit ringdown. The 256-entry table also caps the length: "
    "the designer stops at 255 half cycles, so at 3 MHz mean frequency the "
    "usable maximum is ~42 us.\n\n"
    "Element/frame timing grows with it - the readout updates accordingly.",

"element":
    "Which element to fire when 'single element' is ticked.\n\n"
    "0-47 is an APERTURE POSITION: 0 is the left-most element of the array, 47 "
    "the right-most. It is not a mux address - the connector wiring is "
    "scrambled, and tx_sequencer.v's mux_code() table maps the position onto "
    "the root/leaf switch pair that actually reaches it.\n\n"
    "This is also the id that arrives in the frame header, so it indexes the "
    "element geometry in tfm_gl_host.py directly.\n\n"
    "Moving this slider sends nothing unless 'single element' is ticked.",
}


class _Tip:
    """One shared hover popup, positioned under the widget it describes.

    Deliberately a single reusable Toplevel rather than one per control: the
    panel has a dozen widgets and Tk is happier with one window that moves.
    """
    DELAY_MS = 450
    WRAP_PX  = 360

    def __init__(self, root, FG, BG, GRID):
        self.root, self.FG, self.BG, self.GRID = root, FG, BG, GRID
        self.win = None
        self.job = None

    def attach(self, widget, text):
        if not text:
            return
        widget.bind("<Enter>", lambda e, w=widget: self._arm(w, text), add="+")
        widget.bind("<Leave>",      lambda e: self.hide(), add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")

    def _arm(self, widget, text):
        self.hide()
        self.job = self.root.after(self.DELAY_MS,
                                   lambda: self._show(widget, text))

    def hide(self):
        import tkinter as tk
        if self.job is not None:
            try:    self.root.after_cancel(self.job)
            except tk.TclError: pass
            self.job = None
        if self.win is not None:
            try:    self.win.destroy()
            except tk.TclError: pass
            self.win = None

    def _show(self, widget, text):
        import tkinter as tk
        self.job = None
        try:
            if not widget.winfo_exists():
                return
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 4
        except tk.TclError:
            return

        self.win = tk.Toplevel(self.root)
        self.win.wm_overrideredirect(True)          # no title bar / decorations
        self.win.configure(bg=self.GRID)
        tk.Label(self.win, text=text, justify="left", anchor="w",
                 wraplength=self.WRAP_PX, fg=self.FG, bg=self.BG,
                 font=("TkDefaultFont", 8), padx=8, pady=6
                 ).pack(padx=1, pady=1)

        # Keep it on screen: nudge left if it would run off the right edge,
        # flip above the widget if it would run off the bottom.
        self.win.update_idletasks()
        w, hgt = self.win.winfo_width(), self.win.winfo_height()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = max(0, min(x, sw - w - 4))
        if y + hgt > sh:
            y = max(0, widget.winfo_rooty() - hgt - 4)
        self.win.wm_geometry("+%d+%d" % (int(x), int(y)))


# =============================================================================
# Optional Tk panel
# =============================================================================
def build_pulser_panel(parent, ctl, FG="#9ab", BG="#101418", GRID="#1e2a33",
                       on_change=None):
    """Slider panel for the pulser. Returns a dict of the Tk vars.

    Every value quantises to a 100 MHz clock cycle in the FPGA, so dragging a
    slider only emits a command when the QUANTISED value actually changes -
    a drag across a range worth one cycle sends one command, not fifty.
    """
    import tkinter as tk

    btns = tk.Frame(parent, bg=BG); btns.pack(fill="x")
    sl   = tk.Frame(parent, bg=BG); sl.pack(fill="x")

    tip = _Tip(parent.winfo_toplevel(), FG, BG, GRID)

    armv    = tk.BooleanVar(value=ctl.arm)
    singlev = tk.BooleanVar(value=False)
    info    = tk.Label(btns, text="", fg=FG, bg=BG, anchor="w")

    def refresh():
        info.config(text="f0 %.2f MHz   burst %.0f ns   element %.1f us   frame %.2f ms%s"
                    % (ctl.f0_hz() / 1e6, ctl.burst_ns(),
                       ctl.element_period_us(), ctl.frame_ms(),
                       "" if ctl.arm else "   [STOPPED]"))
        if on_change:
            on_change(ctl)

    def slider(label, frm, to, res, setter, init, quant, row, col, intvar=False):
        """One labelled slider. `quant` maps the UI value to FPGA clock cycles
        so we can skip sends that would not change the hardware."""
        var  = (tk.IntVar if intvar else tk.DoubleVar)(value=init)
        last = {"q": quant(init)}

        def moved(_v):
            q = quant(var.get())
            if q == last["q"]:
                return                  # same clock-cycle value - nothing to send
            last["q"] = q
            setter(var.get())
            refresh()

        w = tk.Scale(sl, from_=frm, to=to, resolution=res, orient="horizontal",
                     variable=var, command=moved, label=label, length=128,
                     bg=BG, fg=FG, troughcolor=GRID, highlightthickness=0,
                     activebackground=GRID, font=("TkDefaultFont", 7))
        w.grid(row=row, column=col, padx=3, pady=(0, 2), sticky="w")
        tip.attach(w, HELP.get(label))
        return var, w

    # --- buttons -------------------------------------------------------------
    def on_arm():
        ctl.set_arm(armv.get()); refresh()

    w_arm = tk.Checkbutton(btns, text="PULSER RUN", variable=armv, command=on_arm,
                           fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                           activeforeground=FG)
    w_arm.pack(side="left", padx=(2, 4))
    tip.attach(w_arm, HELP["PULSER RUN"])

    def set_arm_to(on):
        armv.set(on); ctl.set_arm(on); refresh()

    w_stop = tk.Button(btns, text="STOP", command=lambda: set_arm_to(False), fg=FG,
                       bg=GRID, activebackground=GRID, relief="groove")
    w_stop.pack(side="left", padx=2)
    w_run = tk.Button(btns, text="START", command=lambda: set_arm_to(True), fg=FG,
                      bg=GRID, activebackground=GRID, relief="groove")
    w_run.pack(side="left", padx=2)
    w_fclr = tk.Button(btns, text="clr fault", command=ctl.clear_fault, fg=FG,
                       bg=GRID, activebackground=GRID, relief="groove")
    w_fclr.pack(side="left", padx=(2, 10))
    tip.attach(w_stop, HELP["PULSER RUN"])
    tip.attach(w_run,  HELP["PULSER RUN"])
    tip.attach(w_fclr, HELP["clr fault"])

    def on_single():
        ctl.set_single_elem(elemv.get() if singlev.get() else None)
        refresh()

    w_single = tk.Checkbutton(btns, text="single element", variable=singlev,
                              command=on_single, fg=FG, bg=BG, selectcolor=BG,
                              activebackground=BG, activeforeground=FG)
    w_single.pack(side="left")
    tip.attach(w_single, HELP["single element"])

    chirpv = tk.BooleanVar(value=ctl.chirp_on)

    def on_chirp():
        ctl.set_chirp_on(chirpv.get()); refresh()

    w_chirp = tk.Checkbutton(btns, text="chirp", variable=chirpv,
                             command=on_chirp, fg=FG, bg=BG, selectcolor=BG,
                             activebackground=BG, activeforeground=FG)
    w_chirp.pack(side="left")
    tip.attach(w_chirp, HELP["chirp"])

    info.pack(side="left", padx=(14, 2))

    # --- sliders -------------------------------------------------------------
    # Row 0: burst shape.  Row 1: the inter-stage waits and element selection.
    # settle/inhibit start at their datasheet floors - the FPGA clamps anything
    # lower regardless, so the slider simply cannot ask for an unsafe value.
    ncyc,    w_ncyc    = slider("pulses",      1, 16,  1,   ctl.set_n_cycles,    ctl.n_cycles,
                        lambda v: int(v),  0, 0, intvar=True)
    tdrive,  w_tdrive  = slider("width ns",   10, 500, 10,  ctl.set_t_drive_ns,  ctl.t_drive_ns,
                        ns_to_cyc,         0, 1)
    tdead,   w_tdead   = slider("dead ns",    10, 200, 10,  ctl.set_t_dead_ns,   ctl.t_dead_ns,
                        ns_to_cyc,         0, 2)
    tsettle, w_tsettle = slider("settle us",  T_SETTLE_MIN_US,  40, 0.5, ctl.set_t_settle_us,
                        ctl.t_settle_us,   us_to_cyc,   0, 3)
    tinhib,  w_tinhib  = slider("inhibit us", T_INHIBIT_MIN_US, 40, 0.5, ctl.set_t_inhib_us,
                        ctl.t_inhib_us,    us_to_cyc,   0, 4)

    tring,   w_tring   = slider("ring us",     0, 50,  0.5, ctl.set_t_ring_us,   ctl.t_ring_us,
                        us_to_cyc,         1, 0)
    trx,     w_trx     = slider("rx us",      10, 500, 5,   ctl.set_t_rx_us,     ctl.t_rx_us,
                        us_to_cyc,         1, 1)
    nelem,   w_nelem   = slider("elements",    1, N_ELEM_MAX, 1, ctl.set_n_elem, ctl.n_elem,
                        lambda v: int(v),  1, 2, intvar=True)

    # The element slider only transmits while "single element" is ticked;
    # otherwise it just parks a value for when you tick it.
    elemv = tk.IntVar(value=0)
    last_e = {"q": 0}

    def elem_moved(_v):
        if elemv.get() == last_e["q"]:
            return
        last_e["q"] = elemv.get()
        if singlev.get():
            ctl.set_single_elem(elemv.get()); refresh()

    w_elem = tk.Scale(sl, from_=0, to=N_ELEM_MAX - 1, resolution=1,
                      orient="horizontal", variable=elemv, command=elem_moved,
                      label="element", length=128, bg=BG, fg=FG,
                      troughcolor=GRID, highlightthickness=0,
                      activebackground=GRID, font=("TkDefaultFont", 7))
    w_elem.grid(row=1, column=3, padx=3, pady=(0, 2), sticky="w")
    tip.attach(w_elem, HELP["element"])

    # Row 2: coded excitation.  Sliders always track, but only transmit while
    # the chirp checkbox is ticked (each change re-uploads the whole table).
    cf0, w_cf0 = slider("chirp f0 M", 0.5, 8.0, 0.1, ctl.set_chirp_f0_mhz,
                        ctl.chirp_f0_mhz, lambda v: round(float(v), 1), 2, 0)
    cf1, w_cf1 = slider("chirp f1 M", 0.5, 8.0, 0.1, ctl.set_chirp_f1_mhz,
                        ctl.chirp_f1_mhz, lambda v: round(float(v), 1), 2, 1)
    cus, w_cus = slider("chirp us",   1.0, 40.0, 0.5, ctl.set_chirp_us,
                        ctl.chirp_us, lambda v: round(float(v), 1), 2, 2)

    refresh()

    return dict(arm=armv, n_cycles=ncyc, t_drive=tdrive, t_dead=tdead,
                t_settle=tsettle, t_inhib=tinhib, t_ring=tring, t_rx=trx,
                n_elem=nelem, single=singlev, elem=elemv, chirp=chirpv,
                chirp_f0=cf0, chirp_f1=cf1, chirp_us=cus, refresh=refresh,
                tip=tip,
                widgets=dict(pulses=w_ncyc, width=w_tdrive, dead=w_tdead,
                             settle=w_tsettle, inhibit=w_tinhib, ring=w_tring,
                             rx=w_trx, elements=w_nelem, element=w_elem,
                             chirp_f0=w_cf0, chirp_f1=w_cf1, chirp_us=w_cus))


# =============================================================================
# Standalone CLI
# =============================================================================
LOCK_WORD = 0xA5A55A5A          # RX-latency lock word, must be the first write
PIPE_OUT  = 0x02
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10


def _open_ft601():
    """Open the Ft+ and return a send_cmd(word, name) that writes one command."""
    import ctypes as C, os, struct

    dll = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FTD3XX.dll")
    if not os.path.exists(dll):
        raise SystemExit("FTD3XX.dll not found next to this script")
    d3 = C.WinDLL(dll)
    d3.FT_Create.restype    = C.c_ulong
    d3.FT_WritePipe.restype = C.c_ulong

    h = C.c_void_p()
    if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX), C.byref(h)) != FT_OK:
        raise SystemExit("FT_Create failed - is the Ft+ enumerated, and is "
                         "scope_host.py closed?  The FT601 opens exclusively.")
    d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))

    def send_cmd(word, name=""):
        buf  = (C.c_ubyte * 4).from_buffer_copy(struct.pack("<I", word & 0xFFFFFFFF))
        sent = C.c_ulong(0)
        st = d3.FT_WritePipe(h, C.c_ubyte(PIPE_OUT), buf, C.c_ulong(4),
                             C.byref(sent), None)
        if st != FT_OK or sent.value != 4:
            raise SystemExit("control write failed (%s): st=%d sent=%d"
                             % (name, st, sent.value))

    return d3, h, send_cmd


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(
        description="Set transmit sequencer parameters over the FT601 control pipe.",
        epilog="Only the options you pass are sent; everything else is left "
               "as the FPGA already has it. Close scope_host.py first.")
    ap.add_argument("--start",   action="store_true", help="arm the pulser")
    ap.add_argument("--stop",    action="store_true",
                    help="park the driver and assert MUX_CLR (opens every switch)")
    ap.add_argument("--pulses",  type=int,   metavar="N",  help="+/- pulse pairs per burst")
    ap.add_argument("--width",   type=float, metavar="NS", help="width of each +HV/-HV pulse")
    ap.add_argument("--dead",    type=float, metavar="NS", help="gap between polarities")
    ap.add_argument("--settle",  type=float, metavar="US", help="LE rise -> first HV edge")
    ap.add_argument("--inhibit", type=float, metavar="US", help="last pulse -> SPI mux clocking")
    ap.add_argument("--ring",    type=float, metavar="US", help="ringdown blanking")
    ap.add_argument("--rx",      type=float, metavar="US", help="receive window")
    ap.add_argument("--elems",   type=int,   metavar="N",  help="elements per frame")
    ap.add_argument("--chirp",   type=float, nargs=3, metavar=("F0", "F1", "US"),
                    help="coded excitation: linear chirp F0->F1 MHz over US us "
                         "(uploads the table and enables it)")
    ap.add_argument("--chirp-off", action="store_true",
                    help="back to the fixed burst (pulses/width/dead)")
    ap.add_argument("--single",  type=int,   metavar="E",  help="fire only element E")
    ap.add_argument("--walk",    action="store_true", help="undo --single, walk the aperture")
    ap.add_argument("--all",     action="store_true",
                    help="push every setting, not just the ones given")
    ap.add_argument("--clear-fault", action="store_true", help="clear a latched fault")
    ap.add_argument("--show",    action="store_true",
                    help="print the settings and exit without opening the device")
    a = ap.parse_args(argv)

    if a.start and a.stop:
        ap.error("--start and --stop are mutually exclusive")

    # Build the object first so --show needs no hardware.
    pending = []
    ctl = PulserCtl(lambda w, n="": pending.append((n, w)),
                    lambda op, pl=0: ((op & 0xFF) << 24) | (pl & 0xFFFFFF))

    if a.show:
        print(ctl.summary())
        print("\n(defaults as compiled into ctrl_decode.v - there is no readback,")
        print(" so this is not a report of the FPGA's current state)")
        return 0

    d3, h, send = _open_ft601()

    def send_and_log(word, name=""):
        send(word, name)
        pending.append((name, word))
    ctl._send = send_and_log

    print("locking RX window...")
    send(LOCK_WORD, "lock")
    time.sleep(0.05)

    try:
        if a.all:
            ctl.push_all()
        else:
            if a.pulses  is not None: ctl.set_n_cycles(a.pulses)
            if a.width   is not None: ctl.set_t_drive_ns(a.width)
            if a.dead    is not None: ctl.set_t_dead_ns(a.dead)
            if a.settle  is not None: ctl.set_t_settle_us(a.settle)
            if a.inhibit is not None: ctl.set_t_inhib_us(a.inhibit)
            if a.ring    is not None: ctl.set_t_ring_us(a.ring)
            if a.rx      is not None: ctl.set_t_rx_us(a.rx)
            if a.elems   is not None: ctl.set_n_elem(a.elems)
            if a.chirp   is not None:
                ctl.chirp_f0_mhz, ctl.chirp_f1_mhz, ctl.chirp_us = a.chirp
                ctl.set_chirp_on(True)
            if a.chirp_off:           ctl.set_chirp_on(False)
            if a.single  is not None: ctl.set_single_elem(a.single)
            if a.walk:                ctl.set_single_elem(None)
            if a.clear_fault:         ctl.clear_fault()
            if a.stop:                ctl.set_arm(False)
            if a.start:               ctl.set_arm(True)

        if not pending:
            print("nothing to send - pass some options, or --help")
        for name, word in pending:
            print("  sent %-12s 0x%08X" % (name, word))
        if a.all:
            print(ctl.summary())
        elif pending:
            print("%d command(s) sent; every other pulser setting is left "
                  "as the FPGA already had it" % len(pending))
    finally:
        d3.FT_Close(h)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
