# scope_host.py
#   python scope_host.py            -> live oscilloscope + FFT of the AFE5804 stream
#   python scope_host.py signed     -> start in 12-bit two's-complement mode
#
# Streams AFE5804 CH1 (12-bit @ 40 MSPS) from the FPGA over the FT601 fast
# path and draws it like an oscilloscope.  Raw-DLL host, same structure as
# ft601_host.py: control writes on pipe 0x02, overlapped read ring on 0x82.
#
# Wire format (afe_stream.v): little-endian uint16 per sample, in time order.
#   [11:0]  ADC sample     [15:12] rolling sequence tag (increments per sample)
# A break in the sequence tag = samples dropped (FIFO overflow) - counted and
# shown in the status bar, never silently ignored.
#
# Interactions (also summarized in the in-app help line):
#   wheel        zoom time axis (window length) / zoom frequency axis on FFT
#   shift+wheel  zoom vertical scale around the cursor (time plot)
#   drag         pan vertically; pan through history when paused; pan FFT freq
#   ctrl+click   set trigger level at the clicked height
#   double-click reset that plot's view
#   space        pause / resume (paused = freeze + scroll back through history)
import ctypes as C, sys, time, threading
import os, struct
import numpy as np
import tkinter as tk

XFER, NBUF        = 1024*1024, 8
PIPE_IN, PIPE_OUT = 0x82, 0x02
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10

LOCK_WORD = 0xA5A55A5A
OP_START, OP_STOP, OP_RST_CNT, OP_SET_PAT, OP_SET_SRC = 0x01, 0x02, 0x03, 0x04, 0x07
SRC_PATTERN, SRC_ADC = 0, 1

FS_HZ  = 40_000_000         # AFE5804 sample rate (per channel)
NYQ_HZ = FS_HZ / 2

FT_STATUS_NAMES = {
    0: "FT_OK", 1: "FT_INVALID_HANDLE", 2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED", 4: "FT_IO_ERROR", 5: "FT_INSUFFICIENT_RESOURCES",
    6: "FT_INVALID_PARAMETER", 16: "FT_INVALID_ARGS", 17: "FT_NOT_SUPPORTED",
    18: "FT_NO_MORE_ITEMS", 19: "FT_TIMEOUT", 20: "FT_OPERATION_ABORTED",
    21: "FT_RESERVED_PIPE", 22: "FT_INVALID_CONTROL_REQUEST",
}
def ft_status(st): return FT_STATUS_NAMES.get(st, f"0x{st:X}")

dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FTD3XX.dll")
d3 = C.WinDLL(dll_path)
d3.FT_Create.restype    = C.c_ulong
d3.FT_WritePipe.restype = C.c_ulong

class OVERLAPPED(C.Structure):
    _fields_ = [("Internal", C.c_void_p), ("InternalHigh", C.c_void_p),
                ("Pointer",  C.c_void_p), ("hEvent",       C.c_void_p)]

h = C.c_void_p()
if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX), C.byref(h)) != FT_OK:
    sys.exit("FT_Create failed -- is the Ft+ enumerated?")

d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))

def send_cmd(word, name=""):
    buf  = (C.c_ubyte * 4).from_buffer_copy(struct.pack("<I", word & 0xFFFFFFFF))
    sent = C.c_ulong(0)
    st = d3.FT_WritePipe(h, C.c_ubyte(PIPE_OUT), buf, C.c_ulong(4),
                         C.byref(sent), None)
    if st != FT_OK or sent.value != 4:
        sys.exit(f"control write failed ({name}): "
                 f"st={st} ({ft_status(st)}) sent={sent.value}")

def cmd(op, payload=0):
    return ((op & 0xFF) << 24) | (payload & 0xFFFFFF)

start_signed = any(a.lower().startswith("sig") for a in sys.argv[1:])

# --- bring-up ----------------------------------------------------------------
print("locking RX window (0xA5A55A5A)...")
send_cmd(LOCK_WORD, "lock")
time.sleep(0.05)
send_cmd(cmd(OP_SET_SRC, SRC_ADC), "set_src")
send_cmd(cmd(OP_RST_CNT), "rst_cnt")        # implies STOP, zeroes word count

d3.FT_SetStreamPipe(h, C.c_int(0), C.c_int(0), C.c_ubyte(PIPE_IN), C.c_ulong(XFER))
d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_IN), C.c_ulong(1000))

bufs  = [(C.c_ubyte * XFER)() for _ in range(NBUF)]
views = [np.frombuffer(b, dtype=np.uint16) for b in bufs]   # zero-copy
ovs   = [OVERLAPPED() for _ in range(NBUF)]
got   = [C.c_ulong(0) for _ in range(NBUF)]

def queue(i):
    d3.FT_ReadPipeEx(h, C.c_ubyte(PIPE_IN), bufs[i], C.c_ulong(XFER),
                     C.byref(got[i]), C.byref(ovs[i]))

for i in range(NBUF):
    d3.FT_InitializeOverlapped(h, C.byref(ovs[i]))
    queue(i)

send_cmd(cmd(OP_START), "start")            # ring armed first, THEN start

# --- shared state: reader thread <-> UI ---------------------------------------
RING_N   = 1 << 21                          # ~52 ms of history to scroll through
ring     = np.zeros(RING_N, dtype=np.uint16)
ring_wr  = 0                                # total samples ever written
ring_lk  = threading.Lock()

stats = {"bytes": 0, "win_bytes": 0, "t0": time.perf_counter(),
         "mbps": 0.0, "gap_events": 0, "last_seq": None, "alive": True}

def reader():
    global ring_wr
    n = C.c_ulong(0)
    while stats["alive"]:
        for i in range(NBUF):
            if d3.FT_GetOverlappedResult(h, C.byref(ovs[i]), C.byref(n),
                                         C.c_int(1)) != FT_OK:
                if stats["alive"]:
                    print("read error - stream stopped")
                    stats["alive"] = False
                return
            nb = n.value
            ns = nb // 2
            if ns:
                w   = views[i][:ns]
                seq = (w >> 12).astype(np.int16)
                d   = np.diff(seq) & 0xF
                if stats["last_seq"] is not None:
                    first = (int(seq[0]) - stats["last_seq"]) & 0xF
                    if first != 1: stats["gap_events"] += 1
                stats["gap_events"] += int(np.count_nonzero(d != 1))
                stats["last_seq"]    = int(seq[-1])

                with ring_lk:
                    p = ring_wr % RING_N
                    k = min(ns, RING_N - p)
                    ring[p:p+k]    = w[:k]
                    if ns > k: ring[:ns-k] = w[k:]
                    ring_wr += ns
                stats["bytes"]     += nb
                stats["win_bytes"] += nb
            queue(i)
        dt = time.perf_counter() - stats["t0"]
        if dt >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt / 1e6
            stats["win_bytes"], stats["t0"] = 0, time.perf_counter()

t = threading.Thread(target=reader, daemon=True)
t.start()

#===============================================================================
# UI
#===============================================================================
W        = 1080
TH, FH   = 430, 260                          # time / FFT canvas heights
ML, MR, MT, MB = 64, 16, 14, 30              # plot margins
PW       = W - ML - MR
TPH, FPH = TH - MT - MB, FH - MT - MB

NWIN_MIN, NWIN_MAX = 256, 1 << 18
DB_TOP, DB_BOT     = 0.0, -110.0
FFT_MAX_N          = 32768

BG, PLOT_BG, GRID, FRAME = "#101418", "#0a0e12", "#1e2a33", "#33505f"
FG, DIM, TRACE, SPEC     = "#9ab", "#567", "#39d353", "#4db8ff"

def clamp(v, a, b): return max(a, min(b, v))

view = {
    "nwin": 8192,               # samples across the time plot
    "ylo": None, "yhi": None,   # None = autoscale
    "pan": 0,                   # samples back from newest (paused only)
    "fmin": 0.0, "fmax": NYQ_HZ,
    "avg": None,                # running average spectrum
    "frozen": None,             # ring snapshot while paused
}

root = tk.Tk()
root.title("AFE5804 scope - FT601 stream @ 40 MSPS")
root.configure(bg=BG)

top = tk.Frame(root, bg=BG); top.pack(fill="x", padx=6, pady=4)

trig_on  = tk.BooleanVar(value=True)
trig_lvl = tk.IntVar(value=2048)            # raw 0..4095, offset-binary
paused   = tk.BooleanVar(value=False)
signedv  = tk.BooleanVar(value=start_signed)
fft_avg  = tk.BooleanVar(value=False)

def chk(text, var, cmd=None):
    tk.Checkbutton(top, text=text, variable=var, command=cmd, fg=FG, bg=BG,
                   selectcolor=BG, activebackground=BG,
                   activeforeground=FG).pack(side="left", padx=6)

chk("trigger", trig_on)
tk.Label(top, text="level", fg=FG, bg=BG).pack(side="left", padx=(10, 2))
tk.Scale(top, from_=0, to=4095, orient="horizontal", variable=trig_lvl,
         length=150, bg=BG, fg=FG, highlightthickness=0).pack(side="left")

def on_signed():                            # keep view sane across mode flips
    view["ylo"] = view["yhi"] = None
chk("signed", signedv, on_signed)
chk("FFT avg", fft_avg)

def snapshot_ring():
    with ring_lk:
        wr = ring_wr
        p  = wr % RING_N
        if wr < RING_N: return ring[:p].copy()
        return np.concatenate((ring[p:], ring[:p]))

def on_pause():
    if paused.get():
        view["frozen"] = snapshot_ring()
        view["pan"]    = 0
    else:
        view["frozen"] = None
chk("pause", paused, on_pause)

def toggle_pause(_ev=None):
    paused.set(not paused.get()); on_pause()

def reset_time_view():
    view["nwin"] = 8192
    view["ylo"] = view["yhi"] = None
    view["pan"] = 0

def reset_fft_view():
    view["fmin"], view["fmax"] = 0.0, NYQ_HZ

tk.Button(top, text="reset view", command=lambda: (reset_time_view(),
          reset_fft_view()), fg=FG, bg=BG, activebackground=GRID,
          activeforeground=FG, relief="groove").pack(side="left", padx=10)

wininfo = tk.Label(top, text="", fg=DIM, bg=BG, font=("Consolas", 9))
wininfo.pack(side="right")

cv = tk.Canvas(root, width=W, height=TH, bg=PLOT_BG, highlightthickness=0)
cv.pack(padx=6, pady=(2, 0))
fv = tk.Canvas(root, width=W, height=FH, bg=PLOT_BG, highlightthickness=0)
fv.pack(padx=6, pady=(4, 0))

help_line = tk.Label(root, fg=DIM, bg=BG, font=("Consolas", 8), anchor="w",
    text=" wheel: zoom X | shift+wheel: zoom Y | drag: pan | "
         "ctrl+click: trigger level | double-click: reset | space: pause")
help_line.pack(fill="x", padx=6)

status = tk.Label(root, text="starting...", fg="#7f8", bg=BG,
                  font=("Consolas", 10), anchor="w")
status.pack(side="bottom", fill="x", padx=6, pady=2)

def build_grid(c, ph):
    for i in range(11):
        x = ML + PW * i / 10
        c.create_line(x, MT, x, MT + ph, fill=GRID)
    for i in range(9):
        y = MT + ph * i / 8
        c.create_line(ML, y, ML + PW, y, fill=GRID)
    c.create_rectangle(ML, MT, ML + PW, MT + ph, outline=FRAME)

build_grid(cv, TPH)
build_grid(fv, FPH)

trig_line = cv.create_line(ML, 0, ML+PW, 0, fill="#886", dash=(3,3), state="hidden")
trace     = cv.create_line(0, 0, 0, 0, fill=TRACE, width=1)
t_ylabels = [cv.create_text(ML-8, MT+TPH*i/8, anchor="e", fill=DIM,
                            font=("Consolas", 9)) for i in range(9)]
t_xlabel  = cv.create_text(ML+PW/2, MT+TPH+18, fill=DIM, font=("Consolas", 9))
t_cross_v = cv.create_line(0, MT, 0, MT+TPH, fill="#294050", state="hidden")
t_cross_h = cv.create_line(ML, 0, ML+PW, 0, fill="#294050", state="hidden")
t_readout = cv.create_text(ML+PW-6, MT+12, anchor="e", fill="#8bd",
                           font=("Consolas", 9))
paused_tag = cv.create_text(ML+8, MT+12, anchor="w", fill="#fa5",
                            font=("Consolas", 10, "bold"), text="")

spec      = fv.create_line(0, 0, 0, 0, fill=SPEC, width=1)
f_ylabels = [fv.create_text(ML-8, MT+FPH*i/8, anchor="e", fill=DIM,
                            font=("Consolas", 9)) for i in range(9)]
f_xlabels = [fv.create_text(ML+PW*i/10, MT+FPH+18, fill=DIM,
                            font=("Consolas", 9)) for i in range(11)]
f_peak_m  = fv.create_line(0, MT, 0, MT+FPH, fill="#b8860b", dash=(2,3),
                           state="hidden")
f_peak_t  = fv.create_text(ML+PW-6, MT+12, anchor="e", fill="#fd7",
                           font=("Consolas", 9))
f_cross_v = fv.create_line(0, MT, 0, MT+FPH, fill="#294050", state="hidden")
f_readout = fv.create_text(ML+8, MT+12, anchor="w", fill="#8bd",
                           font=("Consolas", 9))

#-------------------------------------------------------------------------------
# data access / decode
#-------------------------------------------------------------------------------
def decode(raw):
    v = (raw & 0x0FFF).astype(np.int32)
    if signedv.get():
        v = np.where(v >= 2048, v - 4096, v)
    return v

def disp_trig_level():
    return trig_lvl.get() - 2048 if signedv.get() else trig_lvl.get()

def full_scale():
    return (-2048, 2047) if signedv.get() else (0, 4095)

def get_raw(grab):
    """Newest `grab` samples, honouring pause + pan."""
    if paused.get() and view["frozen"] is not None:
        fr  = view["frozen"]
        end = len(fr) - view["pan"]
        if end < NWIN_MIN: return None
        return fr[max(0, end-grab):end]
    with ring_lk:
        wr = ring_wr
        if wr < grab:
            if wr < NWIN_MIN: return None
            grab = wr
        p = wr % RING_N
        if p >= grab: return ring[p-grab:p].copy()
        return np.concatenate((ring[RING_N-(grab-p):], ring[:p]))

#-------------------------------------------------------------------------------
# render
#-------------------------------------------------------------------------------
last_wnd = None                              # samples currently on screen

def y_px(vv, lo, hi):
    return MT + TPH * (1.0 - (vv - lo) / float(hi - lo))

def render_time():
    global last_wnd
    nwin = view["nwin"]
    raw  = get_raw(min(RING_N, nwin * 3))
    if raw is None: return
    v = decode(raw)

    start = max(0, v.size - nwin)
    if trig_on.get() and v.size > nwin:
        pre  = nwin // 4
        lvl  = disp_trig_level()
        hunt = v[pre : v.size - (nwin - pre)]
        x = np.nonzero((hunt[:-1] < lvl) & (hunt[1:] >= lvl))[0]
        if x.size: start = int(x[0])         # trigger sits 1/4 from the left
    wnd = v[start:start + nwin]
    if wnd.size < 2: return
    last_wnd = wnd

    if view["ylo"] is None:
        lo, hi = int(wnd.min()), int(wnd.max())
        pad = max(8, (hi - lo) // 8)
        lo, hi = lo - pad, hi + pad
    else:
        lo, hi = view["ylo"], view["yhi"]
    if hi <= lo: hi = lo + 1

    if trig_on.get():
        ly = y_px(disp_trig_level(), lo, hi)
        if MT <= ly <= MT+TPH:
            cv.itemconfigure(trig_line, state="normal")
            cv.coords(trig_line, ML, ly, ML+PW, ly)
        else:
            cv.itemconfigure(trig_line, state="hidden")
    else:
        cv.itemconfigure(trig_line, state="hidden")

    # min/max decimation so fast edges stay visible
    if wnd.size > 2 * PW:
        m   = (wnd.size // PW) * PW
        blk = wnd[:m].reshape(PW, -1)
        yy  = np.empty(2 * PW, dtype=np.int32)
        yy[0::2] = blk.min(axis=1); yy[1::2] = blk.max(axis=1)
        xs  = np.repeat(np.linspace(ML, ML + PW, PW), 2)
    else:
        yy = wnd
        xs = np.linspace(ML, ML + PW, wnd.size)

    ys  = np.clip(MT + TPH * (1.0 - (yy - lo) / float(hi - lo)), MT-2, MT+TPH+2)
    pts = np.empty(2 * len(xs)); pts[0::2] = xs; pts[1::2] = ys
    cv.coords(trace, *pts.tolist())

    for i, l in enumerate(t_ylabels):
        cv.itemconfigure(l, text=f"{hi - (hi - lo) * i / 8:.0f}")
    cv.itemconfigure(t_xlabel,
        text=f"{nwin/FS_HZ*1e6:.4g} us total   ({nwin/FS_HZ*1e6/10:.4g} us/div)")
    cv.itemconfigure(paused_tag,
        text=(f"PAUSED  (-{view['pan']/FS_HZ*1e3:.2f} ms)" if paused.get() else ""))
    wininfo.config(text=f"window {nwin} samp | "
                        f"{'auto' if view['ylo'] is None else 'manual'} Y")
    return lo, hi

def render_fft():
    if last_wnd is None: return
    w = last_wnd
    if w.size > FFT_MAX_N: w = w[-FFT_MAX_N:]
    n = w.size
    if n < 64: return

    x   = w.astype(np.float64) - w.mean()
    win = np.hanning(n)
    X   = np.fft.rfft(x * win)
    # amplitude in dB relative to a full-scale (2048-count) sine
    mag = np.abs(X) * (2.0 / (win.sum() * 2048.0))
    db  = 20.0 * np.log10(np.maximum(mag, 1e-9))
    db  = np.clip(db, DB_BOT, DB_TOP)
    fr  = np.fft.rfftfreq(n, 1.0 / FS_HZ)

    if fft_avg.get():
        a = view["avg"]
        view["avg"] = db if (a is None or len(a) != len(db)) else 0.85*a + 0.15*db
        db = view["avg"]
    else:
        view["avg"] = None

    fmin, fmax = view["fmin"], view["fmax"]
    sel = (fr >= fmin) & (fr <= fmax)
    fs_, ds_ = fr[sel], db[sel]
    if fs_.size < 2: return

    if ds_.size > PW:                        # max-decimate: keep the peaks
        m   = (ds_.size // PW) * PW
        dsr = ds_[:m].reshape(PW, -1).max(axis=1)
        fsr = fs_[:m].reshape(PW, -1)[:, 0]
    else:
        dsr, fsr = ds_, fs_

    xs  = ML + PW * (fsr - fmin) / (fmax - fmin)
    ys  = MT + FPH * (DB_TOP - dsr) / (DB_TOP - DB_BOT)
    pts = np.empty(2 * len(xs)); pts[0::2] = xs; pts[1::2] = ys
    fv.coords(spec, *pts.tolist())

    for i, l in enumerate(f_ylabels):
        fv.itemconfigure(l, text=f"{DB_TOP - (DB_TOP-DB_BOT)*i/8:.0f}")
    for i, l in enumerate(f_xlabels):
        f = fmin + (fmax - fmin) * i / 10
        fv.itemconfigure(l, text=f"{f/1e6:.4g}" if i % 2 == 0 else "")
    fv.itemconfigure(f_xlabels[5],
        text=f"{(fmin+(fmax-fmin)/2)/1e6:.4g} MHz")

    # peak marker (ignore near-DC)
    pk = np.nonzero(fs_ > max(fmin, 50e3))[0]
    if pk.size:
        j  = pk[np.argmax(ds_[pk])]
        px = ML + PW * (fs_[j] - fmin) / (fmax - fmin)
        fv.itemconfigure(f_peak_m, state="normal")
        fv.coords(f_peak_m, px, MT, px, MT + FPH)
        fv.itemconfigure(f_peak_t,
            text=f"peak {fs_[j]/1e6:.4f} MHz  {ds_[j]:.1f} dBFS")

#-------------------------------------------------------------------------------
# interactions
#-------------------------------------------------------------------------------
mouse = {"cv": None, "x": 0, "y": 0, "drag": None, "ylohi": None}
cur_lohi = [full_scale()]                    # last rendered y-range, for cursors

def widget_at(ev):
    return root.winfo_containing(ev.x_root, ev.y_root)

def canv_xy(c, ev):
    return ev.x_root - c.winfo_rootx(), ev.y_root - c.winfo_rooty()

def materialize_y():
    if view["ylo"] is None:
        view["ylo"], view["yhi"] = cur_lohi[0]

def on_wheel(ev):
    w = widget_at(ev)
    up = ev.delta > 0
    if w is cv:
        x, _ = canv_xy(cv, ev)
        frac = clamp((x - ML) / PW, 0.0, 1.0)
        old  = view["nwin"]
        new  = clamp(int(old / 1.3) if up else int(old * 1.3), NWIN_MIN, NWIN_MAX)
        if paused.get():                     # keep the sample under the cursor
            view["pan"] = clamp(view["pan"] + int((old-new) * (1.0-frac)),
                                0, RING_N - NWIN_MIN)
        view["nwin"] = new
    elif w is fv:
        x, _ = canv_xy(fv, ev)
        frac = clamp((x - ML) / PW, 0.0, 1.0)
        fmin, fmax = view["fmin"], view["fmax"]
        span = fmax - fmin
        new  = clamp(span / 1.4 if up else span * 1.4, 100e3, NYQ_HZ)
        fc   = fmin + span * frac
        view["fmin"] = clamp(fc - new * frac, 0.0, NYQ_HZ - new)
        view["fmax"] = view["fmin"] + new

def on_shift_wheel(ev):
    if widget_at(ev) is not cv: return
    materialize_y()
    _, y = canv_xy(cv, ev)
    lo, hi = view["ylo"], view["yhi"]
    frac = clamp(1.0 - (y - MT) / TPH, 0.0, 1.0)
    vc   = lo + (hi - lo) * frac
    span = (hi - lo) * (1/1.3 if ev.delta > 0 else 1.3)
    span = clamp(span, 4, 3 * 4096)
    view["ylo"] = vc - span * frac
    view["yhi"] = view["ylo"] + span

def on_press(ev, c):
    if ev.state & 0x4:                       # Ctrl held -> set trigger level
        if c is cv:
            _, y = canv_xy(cv, ev)
            lo, hi = cur_lohi[0]
            val = lo + (hi - lo) * clamp(1.0 - (y - MT) / TPH, 0.0, 1.0)
            raw = val + 2048 if signedv.get() else val
            trig_lvl.set(int(clamp(raw, 0, 4095)))
        return
    mouse["drag"]  = (c, ev.x, ev.y)
    materialize_y()
    mouse["ylohi"] = (view["ylo"], view["yhi"])
    mouse["fspan"] = (view["fmin"], view["fmax"])
    mouse["pan0"]  = view["pan"]

def on_drag(ev, c):
    if not mouse["drag"] or mouse["drag"][0] is not c: return
    dx, dy = ev.x - mouse["drag"][1], ev.y - mouse["drag"][2]
    if c is cv:
        lo, hi = mouse["ylohi"]
        dv = (hi - lo) * dy / TPH
        view["ylo"], view["yhi"] = lo + dv, hi + dv   # trace follows the cursor
        if paused.get() and view["frozen"] is not None:
            dpan = int(view["nwin"] * dx / PW)
            view["pan"] = clamp(mouse["pan0"] + dpan, 0,
                                max(0, len(view["frozen"]) - view["nwin"]))
    else:
        fmin, fmax = mouse["fspan"]
        df = (fmax - fmin) * dx / PW
        nf = clamp(fmin - df, 0.0, NYQ_HZ - (fmax - fmin))
        view["fmin"], view["fmax"] = nf, nf + (fmax - fmin)

def on_release(_ev):
    mouse["drag"] = None

def on_motion(ev, c):
    mouse["cv"], (mouse["x"], mouse["y"]) = c, canv_xy(c, ev)

def on_leave(_ev):
    mouse["cv"] = None

def on_dblclick(_ev, c):
    if c is cv: reset_time_view()
    else:       reset_fft_view()

root.bind_all("<MouseWheel>",       on_wheel)
root.bind_all("<Shift-MouseWheel>", on_shift_wheel)
root.bind_all("<space>",            toggle_pause)
for c in (cv, fv):
    c.bind("<Button-1>",        lambda e, c=c: on_press(e, c))
    c.bind("<B1-Motion>",       lambda e, c=c: on_drag(e, c))
    c.bind("<ButtonRelease-1>", on_release)
    c.bind("<Motion>",          lambda e, c=c: on_motion(e, c))
    c.bind("<Leave>",           on_leave)
    c.bind("<Double-Button-1>", lambda e, c=c: on_dblclick(e, c))

def draw_cursors(lohi):
    if mouse["cv"] is cv and ML <= mouse["x"] <= ML+PW and MT <= mouse["y"] <= MT+TPH:
        lo, hi = lohi
        tt = (mouse["x"] - ML) / PW * view["nwin"] / FS_HZ * 1e6
        vv = lo + (hi - lo) * (1.0 - (mouse["y"] - MT) / TPH)
        cv.itemconfigure(t_cross_v, state="normal")
        cv.itemconfigure(t_cross_h, state="normal")
        cv.coords(t_cross_v, mouse["x"], MT, mouse["x"], MT+TPH)
        cv.coords(t_cross_h, ML, mouse["y"], ML+PW, mouse["y"])
        cv.itemconfigure(t_readout, text=f"t={tt:.3f} us   v={vv:.0f}")
    else:
        cv.itemconfigure(t_cross_v, state="hidden")
        cv.itemconfigure(t_cross_h, state="hidden")
        cv.itemconfigure(t_readout, text="")

    if mouse["cv"] is fv and ML <= mouse["x"] <= ML+PW and MT <= mouse["y"] <= MT+FPH:
        ff = view["fmin"] + (view["fmax"]-view["fmin"]) * (mouse["x"]-ML) / PW
        dd = DB_TOP - (DB_TOP - DB_BOT) * (mouse["y"] - MT) / FPH
        fv.itemconfigure(f_cross_v, state="normal")
        fv.coords(f_cross_v, mouse["x"], MT, mouse["x"], MT+FPH)
        fv.itemconfigure(f_readout, text=f"{ff/1e6:.4f} MHz  {dd:.1f} dB")
    else:
        fv.itemconfigure(f_cross_v, state="hidden")
        fv.itemconfigure(f_readout, text="")

#-------------------------------------------------------------------------------
# main loop
#-------------------------------------------------------------------------------
def update():
    lohi = render_time()
    if lohi: cur_lohi[0] = lohi
    render_fft()
    draw_cursors(cur_lohi[0])

    g = stats["gap_events"]
    status.config(
        text=f" {stats['mbps']:6.1f} MB/s   total {stats['bytes']/1e9:6.2f} GB   "
             f"seq gaps {g}"
             + ("" if stats["alive"] else "   *** STREAM STOPPED ***"),
        fg="#7f8" if g == 0 else "#fa5")
    root.after(33, update)

root.after(100, update)

def on_close():
    stats["alive"] = False
    try:
        send_cmd(cmd(OP_STOP), "stop")
    except SystemExit:
        pass
    time.sleep(0.1)
    for i in range(NBUF):
        d3.FT_ReleaseOverlapped(h, C.byref(ovs[i]))
    d3.FT_Close(h)
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
print("streaming - close the window to stop.")
root.mainloop()
