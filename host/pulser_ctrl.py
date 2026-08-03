# pulser_ctrl.py - transmit sequencer control over the FT601 control pipe.
#
# Mirrors the opcode map and the datasheet floors in tx_sequencer.v and
# ctrl_decode.v.  Import into any host app that already has send_cmd()/cmd():
#
#     from pulser_ctrl import PulserCtl, build_pulser_panel
#     pulser = PulserCtl(send_cmd, cmd)
#     build_pulser_panel(frame, pulser, FG=FG, BG=BG, GRID=GRID)  # optional GUI
#     pulser.push_all()          # make the FPGA agree with the UI
#
# The sequencer free-runs on its own timebase and is NOT gated by START/STOP -
# it keeps firing whether or not the ADC stream is running, and nothing here
# touches the receive path.

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
)


def ns_to_cyc(ns):  return max(1, int(round(float(ns) / NS_PER_CYCLE)))
def us_to_cyc(us):  return max(1, int(round(float(us) * CLK_HZ / 1e6)))
def cyc_to_ns(c):   return c * NS_PER_CYCLE
def cyc_to_us(c):   return c * 1e6 / CLK_HZ


class PulserCtl:
    """Holds the current pulser settings and pushes them to the FPGA."""

    def __init__(self, send_cmd, cmd):
        self._send = send_cmd
        self._cmd  = cmd
        self.__dict__.update(DEFAULTS)
        self.single_elem = None      # None = walk 0..n_elem-1

    # -- derived ---------------------------------------------------------------
    def f0_hz(self):
        """Centre frequency: one cycle is drive/dead/drive/dead."""
        period_ns = 2.0 * (cyc_to_ns(ns_to_cyc(self.t_drive_ns)) +
                           cyc_to_ns(ns_to_cyc(self.t_dead_ns)))
        return 1e9 / period_ns if period_ns > 0 else 0.0

    def burst_ns(self):
        return self.n_cycles * 2.0 * (cyc_to_ns(ns_to_cyc(self.t_drive_ns)) +
                                      cyc_to_ns(ns_to_cyc(self.t_dead_ns)))

    def element_period_us(self):
        """LE fall to LE fall, matching the FSM's state sequence."""
        settle = max(self.t_settle_us, T_SETTLE_MIN_US)
        rx     = self.t_ring_us + self.t_rx_us
        return 0.05 + settle + self.burst_ns() / 1e3 + rx + 0.02

    def frame_ms(self):
        n = 1 if self.single_elem is not None else self.n_elem
        return n * self.element_period_us() / 1e3

    # -- setters (each sends one command) --------------------------------------
    def set_arm(self, on):
        self.arm = bool(on)
        self._send(self._cmd(OP_PLS_ARM, 1 if self.arm else 0), "pls_arm")

    def set_n_cycles(self, n):
        self.n_cycles = max(1, min(255, int(n)))
        self._send(self._cmd(OP_PLS_NCYC, self.n_cycles), "pls_ncyc")

    def set_t_drive_ns(self, ns):
        self.t_drive_ns = float(ns)
        self._send(self._cmd(OP_PLS_TDRIVE, ns_to_cyc(ns)), "pls_tdrive")

    def set_t_dead_ns(self, ns):
        self.t_dead_ns = float(ns)
        self._send(self._cmd(OP_PLS_TDEAD, ns_to_cyc(ns)), "pls_tdead")

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
        self.set_arm(self.arm)                   # arm last

    def summary(self):
        w = "elem %d only" % self.single_elem if self.single_elem is not None \
            else "elements 0-%d" % (self.n_elem - 1)
        return ("pulser: %s  %dx(%.0f ns +/- %.0f ns dead) -> f0 %.2f MHz  "
                "burst %.0f ns  settle %.1f us  inhibit %.1f us  "
                "rx %.0f us  %s  frame %.2f ms"
                % ("RUN" if self.arm else "STOPPED", self.n_cycles,
                   cyc_to_ns(ns_to_cyc(self.t_drive_ns)),
                   cyc_to_ns(ns_to_cyc(self.t_dead_ns)),
                   self.f0_hz() / 1e6, self.burst_ns(),
                   self.t_settle_us, self.t_inhib_us, self.t_rx_us,
                   w, self.frame_ms()))


# =============================================================================
# Optional Tk panel
# =============================================================================
def build_pulser_panel(parent, ctl, FG="#9ab", BG="#101418", GRID="#1e2a33",
                       on_change=None):
    """Two compact rows of pulser controls. Returns a dict of the Tk vars."""
    import tkinter as tk

    row1 = tk.Frame(parent, bg=BG); row1.pack(fill="x")
    row2 = tk.Frame(parent, bg=BG); row2.pack(fill="x")

    armv    = tk.BooleanVar(value=ctl.arm)
    ncyc    = tk.IntVar(value=ctl.n_cycles)
    tdrive  = tk.DoubleVar(value=ctl.t_drive_ns)
    tdead   = tk.DoubleVar(value=ctl.t_dead_ns)
    tsettle = tk.DoubleVar(value=ctl.t_settle_us)
    tinhib  = tk.DoubleVar(value=ctl.t_inhib_us)
    tring   = tk.DoubleVar(value=ctl.t_ring_us)
    trx     = tk.DoubleVar(value=ctl.t_rx_us)
    nelem   = tk.IntVar(value=ctl.n_elem)
    singlev = tk.BooleanVar(value=False)
    elemv   = tk.IntVar(value=0)

    info = tk.Label(row2, text="", fg=FG, bg=BG, anchor="w")

    def refresh():
        info.config(text="f0 %.2f MHz   burst %.0f ns   element %.1f us   frame %.2f ms%s"
                    % (ctl.f0_hz() / 1e6, ctl.burst_ns(),
                       ctl.element_period_us(), ctl.frame_ms(),
                       "" if ctl.arm else "   [STOPPED]"))
        if on_change:
            on_change(ctl)

    def num(frame, label, var, setter, width=7, unit=""):
        tk.Label(frame, text=label, fg=FG, bg=BG).pack(side="left", padx=(8, 2))
        e = tk.Entry(frame, textvariable=var, width=width, fg=FG, bg=GRID,
                     insertbackground=FG, relief="flat")
        e.pack(side="left")
        if unit:
            tk.Label(frame, text=unit, fg=FG, bg=BG).pack(side="left", padx=(1, 0))

        def commit(_ev=None):
            try:
                setter(var.get())
            except Exception:
                return
            refresh()
        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)
        return e

    # --- row 1: run/stop + burst shape ---------------------------------------
    def on_arm():
        ctl.set_arm(armv.get())
        refresh()

    tk.Checkbutton(row1, text="PULSER RUN", variable=armv, command=on_arm,
                   fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                   activeforeground=FG).pack(side="left", padx=(2, 4))

    def stop_now():
        armv.set(False); ctl.set_arm(False); refresh()

    def start_now():
        armv.set(True); ctl.set_arm(True); refresh()

    tk.Button(row1, text="STOP", command=stop_now, fg=FG, bg=GRID,
              activebackground=GRID, relief="groove").pack(side="left", padx=2)
    tk.Button(row1, text="START", command=start_now, fg=FG, bg=GRID,
              activebackground=GRID, relief="groove").pack(side="left", padx=2)
    tk.Button(row1, text="clr fault", command=ctl.clear_fault, fg=FG, bg=GRID,
              activebackground=GRID, relief="groove").pack(side="left", padx=(2, 8))

    num(row1, "pulses",   ncyc,   ctl.set_n_cycles,   width=4)
    num(row1, "width",    tdrive, ctl.set_t_drive_ns, unit="ns")
    num(row1, "dead",     tdead,  ctl.set_t_dead_ns,  unit="ns")

    # --- row 2: the waits + element selection --------------------------------
    num(row2, "settle",  tsettle, ctl.set_t_settle_us, unit="us")
    num(row2, "inhibit", tinhib,  ctl.set_t_inhib_us,  unit="us")
    num(row2, "ring",    tring,   ctl.set_t_ring_us,   unit="us")
    num(row2, "rx",      trx,     ctl.set_t_rx_us,     unit="us")
    num(row2, "elems",   nelem,   ctl.set_n_elem,      width=4)

    def on_single():
        ctl.set_single_elem(elemv.get() if singlev.get() else None)
        refresh()

    tk.Checkbutton(row2, text="single", variable=singlev, command=on_single,
                   fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                   activeforeground=FG).pack(side="left", padx=(8, 0))
    e = tk.Entry(row2, textvariable=elemv, width=4, fg=FG, bg=GRID,
                 insertbackground=FG, relief="flat")
    e.pack(side="left")
    e.bind("<Return>",   lambda _e: on_single())
    e.bind("<FocusOut>", lambda _e: on_single())

    info.pack(side="left", padx=(14, 2))
    refresh()

    return dict(arm=armv, n_cycles=ncyc, t_drive=tdrive, t_dead=tdead,
                t_settle=tsettle, t_inhib=tinhib, t_ring=tring, t_rx=trx,
                n_elem=nelem, single=singlev, elem=elemv, refresh=refresh)
