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
    """Slider panel for the pulser. Returns a dict of the Tk vars.

    Every value quantises to a 100 MHz clock cycle in the FPGA, so dragging a
    slider only emits a command when the QUANTISED value actually changes -
    a drag across a range worth one cycle sends one command, not fifty.
    """
    import tkinter as tk

    btns = tk.Frame(parent, bg=BG); btns.pack(fill="x")
    sl   = tk.Frame(parent, bg=BG); sl.pack(fill="x")

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
        return var, w

    # --- buttons -------------------------------------------------------------
    def on_arm():
        ctl.set_arm(armv.get()); refresh()

    tk.Checkbutton(btns, text="PULSER RUN", variable=armv, command=on_arm,
                   fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                   activeforeground=FG).pack(side="left", padx=(2, 4))

    def set_arm_to(on):
        armv.set(on); ctl.set_arm(on); refresh()

    tk.Button(btns, text="STOP", command=lambda: set_arm_to(False), fg=FG,
              bg=GRID, activebackground=GRID, relief="groove").pack(side="left", padx=2)
    tk.Button(btns, text="START", command=lambda: set_arm_to(True), fg=FG,
              bg=GRID, activebackground=GRID, relief="groove").pack(side="left", padx=2)
    tk.Button(btns, text="clr fault", command=ctl.clear_fault, fg=FG, bg=GRID,
              activebackground=GRID, relief="groove").pack(side="left", padx=(2, 10))

    def on_single():
        ctl.set_single_elem(elemv.get() if singlev.get() else None)
        refresh()

    tk.Checkbutton(btns, text="single element", variable=singlev,
                   command=on_single, fg=FG, bg=BG, selectcolor=BG,
                   activebackground=BG, activeforeground=FG).pack(side="left")

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

    tk.Scale(sl, from_=0, to=N_ELEM_MAX - 1, resolution=1, orient="horizontal",
             variable=elemv, command=elem_moved, label="element", length=128,
             bg=BG, fg=FG, troughcolor=GRID, highlightthickness=0,
             activebackground=GRID, font=("TkDefaultFont", 7)
             ).grid(row=1, column=3, padx=3, pady=(0, 2), sticky="w")

    refresh()

    return dict(arm=armv, n_cycles=ncyc, t_drive=tdrive, t_dead=tdead,
                t_settle=tsettle, t_inhib=tinhib, t_ring=tring, t_rx=trx,
                n_elem=nelem, single=singlev, elem=elemv, refresh=refresh,
                widgets=dict(pulses=w_ncyc, width=w_tdrive, dead=w_tdead,
                             settle=w_tsettle, inhibit=w_tinhib, ring=w_tring,
                             rx=w_trx, elements=w_nelem))


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
