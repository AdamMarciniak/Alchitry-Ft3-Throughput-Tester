# waterfall_host.py
#   python waterfall_host.py            -> live 32-element pulse/receive waterfall
#   python waterfall_host.py signed     -> treat samples as 12-bit two's complement
#
# Drives the FPGA pulse/receive sequencer (SRC_SEQ).  Per element 0-31 the
# FPGA: waits the damp gap (DAC ring-out after the previous window's TGC
# snap back to min), "fires" the element (pretend - no pulser IO yet), waits
# the pulse->receive delay, then captures one TGC-ramped receive window and
# streams it back tagged with the element id.  Raw-DLL host, same structure
# as scope_host.py: control writes on pipe 0x02, overlapped read ring on 0x82.
#
# Wire format (ctrl_decode.v SRC_SEQ), all little-endian 32-bit words:
#   word 0             : 0xE1<<24 | elem<<16 | frame_count      (frame header)
#   word 1..WIN_WORDS  : ADC pairs; per little-endian uint16 sample:
#                          [11:0] sample   [15:12] rolling sequence tag
# frame_count jumps = dropped frames, counted in the status bar.
#
# Display: all 32 receive windows side by side - element across X, time of
# flight down Y (us on the left, tissue depth in cm on the right, assuming
# 1540 m/s round trip), brightness = |amplitude|.  Windows are kept at full
# sample resolution and decimated per redraw, so the depth axis can be zoomed
# (wheel) and panned (drag) down to one sample per pixel.  Click a column to
# see that element's raw trace in the plot below (same zoom range).
#
# Adjustable live: pulse->receive delay, receive-end->pulse damp (DAC ring
# settling), TGC min/max DAC codes.  Adjusting depth restarts the stream
# (the frame size changes) - expect a brief resync blip.
#
# AFE5804 signal-path settings (PGA, LPF, test patterns) are not touched here;
# configure them with scope_host.py first if needed - they persist in the AFE.
import ctypes as C, sys, time, threading
import os, struct
import numpy as np
import tkinter as tk

XFER, NBUF        = 1024*1024, 8
PIPE_IN, PIPE_OUT = 0x82, 0x02
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10

LOCK_WORD = 0xA5A55A5A
OP_START, OP_STOP, OP_RST_CNT = 0x01, 0x02, 0x03
OP_SET_SRC = 0x07
OP_SEQ_LEN, OP_SEQ_DLY, OP_SEQ_TGC = 0x0B, 0x0C, 0x0D
OP_SEQ_GAP, OP_SEQ_TGC0 = 0x0E, 0x0F
SRC_SEQ = 2
CLK_HZ = 100_000_000        # FPGA clk_in - delay payloads are in these cycles
FS_HZ  = 40_000_000         # AFE5804 sample rate

N_ELEM   = 32
C_TISSUE = 1540.0           # m/s, soft tissue - sets the depth <-> time scale

DEPTH_CM_DEF = 8            # ~104 us window, close to the old fixed default
DLY_US_DEF   = 5            # pulse -> receive settling
GAP_US_DEF   = 50           # receive end -> next pulse (DAC ring-out)
TGC_MIN_DEF, TGC_MAX_DEF = 0, 4095

def depth_to_words(cm):
    t = 2.0 * cm / 100.0 / C_TISSUE            # round trip seconds
    return max(320, min(0xFFFF, int(t * FS_HZ) // 2))

cfg = {}                    # everything derived from the window length
def set_cfg(words):
    samps = 2 * words
    cfg.update(win_words=words, samps=samps, frame_words=words + 1,
               win_us=samps / FS_HZ * 1e6)
set_cfg(depth_to_words(DEPTH_CM_DEF))

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

mode = {"signed": any(a.lower().startswith("sig") for a in sys.argv[1:])}

def us_to_cycles(us): return int(us) * (CLK_HZ // 1_000_000)

def send_seq_config(lo, hi, dly_us, gap_us):
    """Push the full sequencer timing/TGC setup for the current window length."""
    inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
    send_cmd(cmd(OP_SEQ_LEN, cfg["win_words"]), "seq_len")
    send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(dly_us)), "seq_dly")
    send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(gap_us)), "seq_gap")
    send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
    send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

# --- bring-up ----------------------------------------------------------------
print("locking RX window (0xA5A55A5A)...")
send_cmd(LOCK_WORD, "lock")
time.sleep(0.05)
send_cmd(cmd(OP_RST_CNT), "rst_cnt")        # implies STOP, zeroes word count
send_cmd(cmd(OP_SET_SRC, SRC_SEQ), "set_src")
send_seq_config(TGC_MIN_DEF, TGC_MAX_DEF, DLY_US_DEF, GAP_US_DEF)

d3.FT_SetStreamPipe(h, C.c_int(0), C.c_int(0), C.c_ubyte(PIPE_IN), C.c_ulong(XFER))
d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_IN), C.c_ulong(1000))

bufs  = [(C.c_ubyte * XFER)() for _ in range(NBUF)]
views = [np.frombuffer(b, dtype=np.uint32) for b in bufs]   # zero-copy
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
# buf_lk guards cfg, the buffers, and the parser state; process() holds it for
# a whole USB chunk so a depth change can swap everything atomically.
buf_lk  = threading.Lock()
raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  # full-res windows
carry   = np.empty(0, dtype=np.uint32)

stats = {"bytes": 0, "win_bytes": 0, "t0": time.perf_counter(), "mbps": 0.0,
         "frames": 0, "win_frames": 0, "fps": 0.0, "drops": 0, "resyncs": 0,
         "last_fcnt": None, "alive": True, "dirty": False}

def batch(fr):
    """fr: (m, frame_words) uint32, all rows verified to start with a header."""
    hdr   = fr[:, 0]
    elems = (hdr >> 16) & 0x1F
    fcnt  = (hdr & 0xFFFF).astype(np.int64)
    if stats["last_fcnt"] is not None and \
       ((int(fcnt[0]) - stats["last_fcnt"]) & 0xFFFF) != 1:
        stats["drops"] += 1
    stats["drops"] += int(np.count_nonzero((np.diff(fcnt) & 0xFFFF) != 1))
    stats["last_fcnt"] = int(fcnt[-1])

    u = (np.ascontiguousarray(fr[:, 1:]).view(np.uint16) & 0x0FFF).astype(np.int32)
    c = np.where(u >= 2048, u - 4096, u) if mode["signed"] else u - 2048
    raw_buf[elems] = c.astype(np.int16)     # keep full resolution; the UI
    stats["frames"]     += fr.shape[0]      # decimates per redraw / zoom
    stats["win_frames"] += fr.shape[0]
    stats["dirty"] = True

def process(words):
    """Frame parser.  Fast path: back-to-back aligned frames, fully vectorized.
    A header is 0xE1 in the top byte with bits 23:21 zero -> top 11 bits 0x708."""
    global carry
    with buf_lk:
        FW = cfg["frame_words"]
        w = np.concatenate((carry, words)) if carry.size else words
        pos, n = 0, w.size
        while n - pos >= FW:
            nfr  = (n - pos) // FW
            hdrs = w[pos : pos + nfr*FW : FW]
            ok   = (hdrs >> 21) == 0x708
            if ok.all():
                batch(w[pos : pos + nfr*FW].reshape(nfr, FW))
                pos += nfr * FW
            else:
                bad = int(np.argmin(ok))            # first non-header
                if bad > 0:
                    batch(w[pos : pos + bad*FW].reshape(bad, FW))
                    pos += bad * FW
                else:                               # lost sync: hunt for a header
                    stats["resyncs"] += 1
                    nxt = np.nonzero((w[pos+1:] >> 21) == 0x708)[0]
                    if nxt.size == 0:
                        pos = n
                        break
                    pos += 1 + int(nxt[0])
        carry = w[pos:].copy()                      # partial frame -> next chunk

def reader():
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
            nw = nb // 4
            if nw:
                process(views[i][:nw])          # done before the buffer requeues
                stats["bytes"]     += nb
                stats["win_bytes"] += nb
            queue(i)
        dt = time.perf_counter() - stats["t0"]
        if dt >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt / 1e6
            stats["fps"]  = stats["win_frames"] / dt
            stats["win_bytes"], stats["win_frames"] = 0, 0
            stats["t0"] = time.perf_counter()

t = threading.Thread(target=reader, daemon=True)
t.start()

#===============================================================================
# UI
#===============================================================================
CW       = 20                                # pixels per element column
IMG_W    = N_ELEM * CW                       # 640
IMG_H    = 560                               # waterfall pixel rows
MIN_SPAN = 64                                # deepest zoom: 64 samples on screen

# visible slice of the receive window, as fractions of the full window -
# survives depth changes; wheel zooms, drag pans, double-click resets
view = {"f0": 0.0, "f1": 1.0}
ML, MR, MT, MB = 56, 52, 10, 30              # right margin fits the cm axis
W        = ML + IMG_W + MR
TH       = 200                               # trace canvas height
TMT, TMB = 12, 26
TPH      = TH - TMT - TMB

BG, PLOT_BG, GRID, FRAME = "#101418", "#0a0e12", "#1e2a33", "#33505f"
FG, DIM, TRACE           = "#9ab", "#567", "#39d353"

# "hot" colormap: black -> red -> yellow -> white
_t  = np.linspace(0.0, 1.0, 256)
LUT = (np.stack([np.clip(_t*3, 0, 1), np.clip(_t*3-1, 0, 1),
                 np.clip(_t*3-2, 0, 1)], axis=1) * 255).astype(np.uint8)

def clamp(v, a, b): return max(a, min(b, v))

root = tk.Tk()
root.title("pulse/receive waterfall - 32 elements  (F11: fullscreen)")
root.configure(bg=BG)

bar1 = tk.Frame(root, bg=BG); bar1.pack(fill="x", padx=6, pady=(4, 0))
bar2 = tk.Frame(root, bg=BG); bar2.pack(fill="x", padx=6, pady=(0, 2))

paused   = tk.BooleanVar(value=False)
signedv  = tk.BooleanVar(value=mode["signed"])
depth_cm = tk.IntVar(value=DEPTH_CM_DEF)
dly_us   = tk.IntVar(value=DLY_US_DEF)
gap_us   = tk.IntVar(value=GAP_US_DEF)
tgc_min  = tk.IntVar(value=TGC_MIN_DEF)
tgc_max  = tk.IntVar(value=TGC_MAX_DEF)
disp_gn  = tk.DoubleVar(value=4.0)
sel_elem = tk.IntVar(value=0)

def chk(parent, text, var, cmd=None):
    tk.Checkbutton(parent, text=text, variable=var, command=cmd, fg=FG, bg=BG,
                   selectcolor=BG, activebackground=BG,
                   activeforeground=FG).pack(side="left", padx=6)

def scale(parent, label, var, lo, hi, cb=None, length=120, res=1):
    tk.Label(parent, text=label, fg=FG, bg=BG).pack(side="left", padx=(10, 2))
    s = tk.Scale(parent, from_=lo, to=hi, resolution=res, orient="horizontal",
                 variable=var, length=length, command=cb, bg=BG, fg=FG,
                 highlightthickness=0)
    s.pack(side="left")
    return s

def on_signed(): mode["signed"] = signedv.get()
chk(bar1, "signed", signedv, on_signed)
chk(bar1, "pause", paused)

def send_tgc(_v=None):
    lo = tgc_min.get()
    hi = max(lo, tgc_max.get())
    inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
    send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
    send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

def send_dly(_v=None): send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(dly_us.get())), "seq_dly")
def send_gap(_v=None): send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(gap_us.get())), "seq_gap")

def apply_depth(_ev=None):
    """Depth changes the frame size: stop, drain, swap buffers, reconfigure."""
    words = depth_to_words(depth_cm.get())
    if words == cfg["win_words"]:
        return
    global raw_buf, carry
    send_cmd(cmd(OP_STOP), "stop")
    time.sleep(0.2)                           # residual old-size frames drain
    with buf_lk:
        set_cfg(words)
        raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)
        carry = np.empty(0, dtype=np.uint32)
        stats["last_fcnt"] = None
    send_seq_config(tgc_min.get(), max(tgc_min.get(), tgc_max.get()),
                    dly_us.get(), gap_us.get())
    send_cmd(cmd(OP_START), "start")
    draw_axes()
    update_wininfo()

# depth applies on slider release, not per tick - it restarts the stream
depth_scale = scale(bar1, "depth cm", depth_cm, 2, 40)
depth_scale.bind("<ButtonRelease-1>", apply_depth)
scale(bar1, "pulse→rx us", dly_us, 0, 500, send_dly)
scale(bar1, "damp us", gap_us, 0, 5000, send_gap)

scale(bar2, "TGC min", tgc_min, 0, 4095, send_tgc, length=160)
scale(bar2, "TGC max", tgc_max, 0, 4095, send_tgc, length=160)
scale(bar2, "display gain", disp_gn, 0.5, 32, length=140, res=0.5)

wininfo = tk.Label(bar2, fg=DIM, bg=BG, font=("Consolas", 9))
wininfo.pack(side="right")

def view_slice():
    """Visible [s0, s1) sample range of the receive window."""
    samps = cfg["samps"]
    s0 = int(view["f0"] * samps)
    s1 = min(samps, max(int(view["f1"] * samps), s0 + 2))
    return s0, s1

def view_us():
    s0, s1 = view_slice()
    return s0 / FS_HZ * 1e6, s1 / FS_HZ * 1e6

def update_wininfo():
    d = cfg["win_us"] * 1e-6 * C_TISSUE / 2 * 100
    t0, t1 = view_us()
    zoom = "full" if view["f0"] == 0.0 and view["f1"] == 1.0 \
           else f"view {t0:.1f}-{t1:.1f} us"
    wininfo.config(text=f"win {cfg['samps']} samp | {cfg['win_us']:.0f} us | "
                        f"{d:.1f} cm | {zoom} | wheel: zoom  drag: pan")
update_wininfo()

# pack bottom-up so the waterfall canvas absorbs all resize slack
status = tk.Label(root, text="starting...", fg="#7f8", bg=BG,
                  font=("Consolas", 10), anchor="w")
status.pack(side="bottom", fill="x", padx=6, pady=2)
tv = tk.Canvas(root, width=W, height=TH, bg=PLOT_BG, highlightthickness=0)
tv.pack(side="bottom", fill="x", padx=6, pady=(4, 2))
cv = tk.Canvas(root, width=W, height=MT+IMG_H+MB, bg=PLOT_BG,
               highlightthickness=0)
cv.pack(fill="both", expand=True, padx=6, pady=(2, 0))

# --- waterfall canvas furniture (rebuilt on every resize) ----------------------
photo_ref = [None]                           # keep the PhotoImage alive
img_item  = None
sel_rect  = None

def nice_step(rng):
    for s in (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if rng / s <= 8: return s
    return 2000

axis_items = []
def draw_axes():
    for it in axis_items: cv.delete(it)
    axis_items.clear()
    t0, t1 = view_us()                       # left: time of flight, us

    def ticks(lo, hi):                       # tick positions within [lo, hi]
        step = nice_step(hi - lo)
        v = np.ceil(lo / step) * step
        while v <= hi + 1e-9:
            yield v, MT + IMG_H * (v - lo) / (hi - lo)
            v += step

    for v, y in ticks(t0, t1):
        axis_items.append(cv.create_line(ML-4, y, ML, y, fill=DIM))
        axis_items.append(cv.create_text(ML-8, y, anchor="e", fill=DIM,
                                         font=("Consolas", 9), text=f"{v:g}"))
    us2cm = 1e-6 * C_TISSUE / 2 * 100        # right: tissue depth, cm
    for v, y in ticks(t0 * us2cm, t1 * us2cm):
        axis_items.append(cv.create_line(ML+IMG_W, y, ML+IMG_W+4, y, fill=DIM))
        axis_items.append(cv.create_text(ML+IMG_W+8, y, anchor="w", fill=DIM,
                                         font=("Consolas", 9), text=f"{v:g}"))
    axis_items.append(cv.create_text(14, MT + IMG_H/2, angle=90, fill=DIM,
        font=("Consolas", 9), text="time of flight (us)"))
    axis_items.append(cv.create_text(ML + IMG_W + MR - 12, MT + IMG_H/2,
        angle=90, fill=DIM, font=("Consolas", 9), text="depth (cm @ 1540 m/s)"))

def build_waterfall():
    global img_item, sel_rect
    cv.delete("all")
    axis_items.clear()
    img_item = cv.create_image(ML, MT, anchor="nw")
    for e in range(0, N_ELEM, 4 if CW >= 14 else 8):    # element axis
        cv.create_text(ML + (e + 0.5) * CW, MT + IMG_H + 12, fill=DIM,
                       font=("Consolas", 9), text=f"{e}")
    cv.create_rectangle(ML, MT, ML+IMG_W, MT+IMG_H, outline=FRAME)
    e = sel_elem.get()
    sel_rect = cv.create_rectangle(ML + e*CW, MT, ML + (e+1)*CW, MT + IMG_H,
                                   outline="#4db8ff", width=2)
    draw_axes()

build_waterfall()

def view_changed():
    draw_axes()
    update_wininfo()
    render_img()                             # redraw immediately (even paused)
    render_trace()

drag = {"y": 0, "f0": 0.0, "moved": False, "x": 0}

def on_wheel(ev):
    # bound on root: on Windows the wheel goes to the focused widget, so
    # locate the pointer ourselves
    if root.winfo_containing(ev.x_root, ev.y_root) is not cv: return
    x, y = ev.x_root - cv.winfo_rootx(), ev.y_root - cv.winfo_rooty()
    if not (ML <= x < ML + IMG_W and MT <= y < MT + IMG_H): return
    span = view["f1"] - view["f0"]
    new  = clamp(span / 1.4 if ev.delta > 0 else span * 1.4,
                 MIN_SPAN / cfg["samps"], 1.0)
    frac = (y - MT) / IMG_H                  # keep the sample under the cursor
    c    = view["f0"] + span * frac
    view["f0"] = clamp(c - new * frac, 0.0, 1.0 - new)
    view["f1"] = view["f0"] + new
    view_changed()

def on_press(ev):
    drag.update(y=ev.y, x=ev.x, f0=view["f0"], moved=False)

def on_drag(ev):
    if abs(ev.y - drag["y"]) + abs(ev.x - drag["x"]) > 3: drag["moved"] = True
    span = view["f1"] - view["f0"]
    df   = (ev.y - drag["y"]) / IMG_H * span
    nf0  = clamp(drag["f0"] - df, 0.0, 1.0 - span)
    if nf0 != view["f0"]:
        view["f0"], view["f1"] = nf0, nf0 + span
        view_changed()

def on_release(ev):
    if drag["moved"]: return                 # it was a pan, not a select
    if ML <= ev.x < ML + IMG_W and MT <= ev.y < MT + IMG_H:
        e = (ev.x - ML) // CW
        sel_elem.set(int(e))
        cv.coords(sel_rect, ML + e*CW, MT, ML + (e+1)*CW, MT + IMG_H)
        render_trace()

def on_reset(_ev):
    view["f0"], view["f1"] = 0.0, 1.0
    view_changed()

root.bind_all("<MouseWheel>", on_wheel)
cv.bind("<Button-1>",         on_press)
cv.bind("<B1-Motion>",        on_drag)
cv.bind("<ButtonRelease-1>",  on_release)
cv.bind("<Double-Button-1>",  on_reset)

# --- trace canvas furniture (rebuilt on every resize) ---------------------------
trace, trace_lbl = None, None

def build_trace():
    global trace, trace_lbl
    tv.delete("all")
    for i in range(11):
        x = ML + IMG_W * i / 10
        tv.create_line(x, TMT, x, TMT + TPH, fill=GRID)
    for i in range(5):
        y = TMT + TPH * i / 4
        tv.create_line(ML, y, ML + IMG_W, y, fill=GRID)
    tv.create_rectangle(ML, TMT, ML+IMG_W, TMT+TPH, outline=FRAME)
    trace     = tv.create_line(0, 0, 0, 0, fill=TRACE, width=1)
    trace_lbl = tv.create_text(ML+8, TMT+12, anchor="w", fill="#8bd",
                               font=("Consolas", 9))
    tv.create_text(ML + IMG_W/2, TMT + TPH + 14, fill=DIM, font=("Consolas", 9),
                   text="selected element receive window (follows waterfall zoom)")

build_trace()

#-------------------------------------------------------------------------------
# render
#-------------------------------------------------------------------------------
def render_img():
    s0, s1 = view_slice()
    with buf_lk:
        a = np.abs(raw_buf[:, s0:s1].astype(np.int32))   # (32, ns) full res
    ns = a.shape[1]
    if ns >= IMG_H:                          # peak-decimate: echoes stay visible
        k   = ns // IMG_H
        col = a[:, :IMG_H*k].reshape(N_ELEM, IMG_H, k).max(axis=2)
    else:                                    # zoomed past 1:1 - replicate samples
        col = a[:, np.arange(IMG_H) * ns // IMG_H]
    disp = np.clip(col.T.astype(np.float32) * (disp_gn.get() * 255.0 / 2048.0),
                   0, 255).astype(np.uint8)              # (IMG_H, 32)
    rgb  = LUT[disp]
    big  = np.repeat(rgb, CW, axis=1)                    # (IMG_H, 640, 3)
    ppm  = b"P6\n%d %d\n255\n" % (IMG_W, IMG_H) + big.tobytes()
    ph   = tk.PhotoImage(data=ppm)
    cv.itemconfigure(img_item, image=ph)
    photo_ref[0] = ph

def render_trace():
    e = sel_elem.get()
    s0, s1 = view_slice()
    with buf_lk:
        w = raw_buf[e, s0:s1].astype(np.int32)
    lo, hi = -2048, 2047                     # samples are centred either way
    if w.size < 2: return
    if w.size >= 2 * IMG_W:
        # min/max decimation so fast echoes stay visible
        m   = (w.size // IMG_W) * IMG_W
        blk = w[:m].reshape(IMG_W, -1)
        yy  = np.empty(2 * IMG_W, dtype=np.int32)
        yy[0::2] = blk.min(axis=1); yy[1::2] = blk.max(axis=1)
        xs  = np.repeat(np.linspace(ML, ML + IMG_W, IMG_W), 2)
    else:                                    # zoomed in: plot samples directly
        yy = w
        xs = np.linspace(ML, ML + IMG_W, w.size)
    ys  = np.clip(TMT + TPH * (1.0 - (yy - lo) / float(hi - lo)),
                  TMT - 2, TMT + TPH + 2)
    pts = np.empty(2 * len(xs)); pts[0::2] = xs; pts[1::2] = ys
    tv.coords(trace, *pts.tolist())
    tv.itemconfigure(trace_lbl,
        text=f"elem {e}   pk {int(np.abs(w).max())}")

#-------------------------------------------------------------------------------
# resize / fullscreen
#-------------------------------------------------------------------------------
resize_job = [None]

def do_relayout():
    global CW, IMG_W, IMG_H, TPH
    resize_job[0] = None
    CW    = max(6, (cv.winfo_width() - ML - MR) // N_ELEM)
    IMG_W = N_ELEM * CW
    IMG_H = max(160, cv.winfo_height() - MT - MB)
    TPH   = max(60, tv.winfo_height() - TMT - TMB)
    build_waterfall()
    build_trace()
    render_img()
    render_trace()

def on_resize(_ev=None):
    # <Configure> fires continuously during a drag-resize; settle first
    if resize_job[0] is not None: root.after_cancel(resize_job[0])
    resize_job[0] = root.after(120, do_relayout)

cv.bind("<Configure>", on_resize)
tv.bind("<Configure>", on_resize)

def toggle_fs(_ev=None):
    root.attributes("-fullscreen", not root.attributes("-fullscreen"))
root.bind("<F11>", toggle_fs)
root.bind("<Escape>", lambda _e: root.attributes("-fullscreen", False))

def update():
    if not paused.get() and stats["dirty"]:
        stats["dirty"] = False
        render_img()
        render_trace()
    status.config(
        text=f" {stats['mbps']:6.1f} MB/s   {stats['fps']/N_ELEM:6.1f} sweeps/s"
             f"   frames {stats['frames']}   frame drops {stats['drops']}"
             f"   resyncs {stats['resyncs']}"
             + ("" if stats["alive"] else "   *** STREAM STOPPED ***"),
        fg="#7f8" if (stats["drops"] == 0 and stats["resyncs"] == 0) else "#fa5")
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
