# tfm_host.py
#   python tfm_host.py            -> live TFM (delay-and-sum) pixel image
#   python tfm_host.py signed     -> treat samples as 12-bit two's complement
#
# Same acquisition path as waterfall_host.py (SRC_SEQ: FPGA fires elements
# 0-31 in turn and streams back one TGC-ramped receive window per fire,
# tagged with the element id).  Instead of a waterfall, this reconstructs a
# 2D pixel image with the Total Focusing Method:
#
#   for every pixel p and element i, the expected round-trip time of flight
#   is 2*|p - elem_i| / c; each element's A-scan is sampled at that delay
#   (minus the pulse->receive delay, since capture starts after it) and all
#   contributions are summed coherently, then envelope-detected and log
#   compressed.  With one receive channel per fire this is the monostatic
#   diagonal of the full FMC matrix (tx == rx), i.e. classic SAFT; the code
#   is written as general tx->pixel->rx TFM so off-diagonal pairs can be
#   added later if per-pair capture shows up.
#
# Geometry: standard convex array, 60 mm radius of curvature, 0.5 mm pitch
# along the arc, apex at (0, 0), elements pointing radially outward.  Each
# element only contributes to pixels within its acceptance cone (aperture
# slider).  Sound speed adjustable around 1540 m/s.
#
# The delay LUT is rebuilt when depth / pulse->rx delay / sound speed /
# aperture change; depth changes restart the stream (frame size changes).
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
C_DEF    = 1540.0           # m/s, soft tissue

PROBE_R_MM   = 60.0         # convex radius of curvature
PITCH_MM     = 0.5          # element pitch along the arc
ACCEPT_DEF   = 30           # element acceptance half-angle, degrees

DEPTH_CM_DEF = 8            # ~104 us window
DLY_US_DEF   = 5            # pulse -> receive settling
GAP_US_DEF   = 50           # receive end -> next pulse (DAC ring-out)
TGC_MIN_DEF, TGC_MAX_DEF = 0, 4095

# element positions/normals, apex of the arc at (0, 0), +z into tissue
_R  = PROBE_R_MM * 1e-3
_th = (np.arange(N_ELEM) - (N_ELEM - 1) / 2.0) * (PITCH_MM / PROBE_R_MM)
EX  = (_R * np.sin(_th)).astype(np.float32)              # lateral, m
EZ  = (_R * (np.cos(_th) - 1.0)).astype(np.float32)      # <= 0: edges curve back
ENX = np.sin(_th).astype(np.float32)                     # outward normals
ENZ = np.cos(_th).astype(np.float32)

def depth_to_words(cm):
    t = 2.0 * cm / 100.0 / C_DEF               # round trip seconds
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
    raw_buf[elems] = c.astype(np.int16)
    stats["frames"]     += fr.shape[0]
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
# TFM delay LUT
#===============================================================================
NX, NZ = 320, 256           # reconstruction grid (square pixels)
SCALE  = 2                  # display magnification
IMG_W, IMG_H = NX * SCALE, NZ * SCALE

# idx[i, p]: sample of element i's A-scan holding the echo from pixel p.
# Validity (pixel inside the window AND inside element i's acceptance cone)
# is folded into idx: invalid entries point at sample `samps`, a permanently
# zero pad column in an_pad, so the render loop is a bare gather+add with no
# mask multiply.
lut = {"idx": None, "cov": 0, "samps": 0, "xw": 0.0, "zmax": 0.0,
       "nfft": 0, "wgt": None, "an_pad": None}

def next_fast_len(n):
    """Smallest 5-smooth number >= n.  np.fft on the raw window length can be
    several times slower (e.g. 4154 = 2*31*67); padding to 2^a*3^b*5^c fixes
    it and only perturbs the Hilbert transform near the window edges."""
    best = 1 << n.bit_length()
    p5 = 1
    while p5 < best:
        p3 = p5
        while p3 < best:
            p2 = p3
            while p2 < n:
                p2 *= 2
            best = min(best, p2)
            p3 *= 3
        p5 *= 5
    return best

def rebuild_lut():
    c     = float(speed.get())
    dly_s = dly_us.get() * 1e-6
    samps = cfg["samps"]
    zmax  = c * (dly_s + cfg["win_us"] * 1e-6) / 2.0     # deepest on-axis echo
    xw    = zmax * NX / NZ                               # square pixels
    xs = ((np.arange(NX, dtype=np.float32) + 0.5) / NX - 0.5) * xw
    zs =  (np.arange(NZ, dtype=np.float32) + 0.5) / NZ * zmax
    px = np.tile(xs, NZ)                                 # flat, row-major (z, x)
    pz = np.repeat(zs, NX)

    dx = px[None, :] - EX[:, None]                       # (32, NX*NZ)
    dz = pz[None, :] - EZ[:, None]
    d  = np.sqrt(dx*dx + dz*dz)
    # tx == rx (monostatic): round trip is 2*d; capture starts dly_s after fire
    idx  = np.rint((2.0 * d / c - dly_s) * FS_HZ).astype(np.int32)
    cosa = (dx * ENX[:, None] + dz * ENZ[:, None]) / np.maximum(d, 1e-9)
    valid = ((idx >= 0) & (idx < samps) &
             (cosa >= np.cos(np.radians(float(accept.get())))))
    idx = np.where(valid, idx, samps).astype(np.int32)   # invalid -> zero pad

    nfft = next_fast_len(samps)
    wgt  = np.zeros(nfft, dtype=np.float32)              # Hilbert spectrum mask
    wgt[0] = 1.0; wgt[nfft//2] = 1.0; wgt[1:nfft//2] = 2.0
    lut.update(idx=idx, cov=int(valid.any(axis=0).sum()), samps=samps,
               xw=xw, zmax=zmax, nfft=nfft, wgt=wgt,
               an_pad=np.zeros((N_ELEM, samps + 1), dtype=np.complex64))

#===============================================================================
# UI
#===============================================================================
ML, MR, MT, MB = 56, 16, 24, 34
W = ML + IMG_W + MR

BG, PLOT_BG, GRID, FRAME = "#101418", "#0a0e12", "#1e2a33", "#33505f"
FG, DIM                  = "#9ab", "#567"

def clamp(v, a, b): return max(a, min(b, v))

root = tk.Tk()
root.title("TFM - 32 element convex, monostatic (SAFT)")
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
speed    = tk.IntVar(value=int(C_DEF))
accept   = tk.IntVar(value=ACCEPT_DEF)
dyn_db   = tk.IntVar(value=50)
gain_db  = tk.IntVar(value=0)

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

def relut(_ev=None):
    """Geometry/timing changed: rebuild the delay LUT and redraw."""
    rebuild_lut()
    draw_axes()
    render_img()

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
    relut()

# depth applies on slider release (restarts the stream); LUT-affecting
# sliders rebuild on release too - a rebuild is ~tens of ms
depth_scale = scale(bar1, "depth cm", depth_cm, 2, 40)
depth_scale.bind("<ButtonRelease-1>", apply_depth)
dly_scale = scale(bar1, "pulse→rx us", dly_us, 0, 500, send_dly)
dly_scale.bind("<ButtonRelease-1>", relut)
scale(bar1, "damp us", gap_us, 0, 5000, send_gap)
scale(bar1, "c m/s", speed, 1400, 1650, length=100).bind("<ButtonRelease-1>", relut)
scale(bar1, "aperture °", accept, 5, 90, length=90).bind("<ButtonRelease-1>", relut)

scale(bar2, "TGC min", tgc_min, 0, 4095, send_tgc, length=150)
scale(bar2, "TGC max", tgc_max, 0, 4095, send_tgc, length=150)
scale(bar2, "dyn range dB", dyn_db, 20, 80, length=110)
scale(bar2, "gain dB", gain_db, -40, 40, length=110)

wininfo = tk.Label(bar2, fg=DIM, bg=BG, font=("Consolas", 9))
wininfo.pack(side="right")

cv = tk.Canvas(root, width=W, height=MT+IMG_H+MB, bg=PLOT_BG,
               highlightthickness=0)
cv.pack(padx=6, pady=(2, 0))

status = tk.Label(root, text="starting...", fg="#7f8", bg=BG,
                  font=("Consolas", 10), anchor="w")
status.pack(side="bottom", fill="x", padx=6, pady=2)

img_item  = cv.create_image(ML, MT, anchor="nw")
photo_ref = [None]                           # keep the PhotoImage alive

def nice_step(rng):
    for s in (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if rng / s <= 10: return s
    return 100

axis_items = []
def draw_axes():
    for it in axis_items: cv.delete(it)
    axis_items.clear()
    xw, zmax = lut["xw"] * 100, lut["zmax"] * 100      # extents in cm

    step = nice_step(zmax)                             # left: depth, cm
    v = 0.0
    while v <= zmax + 1e-9:
        y = MT + IMG_H * v / zmax
        axis_items.append(cv.create_line(ML-4, y, ML, y, fill=DIM))
        axis_items.append(cv.create_text(ML-8, y, anchor="e", fill=DIM,
                                         font=("Consolas", 9), text=f"{v:g}"))
        v += step
    step = nice_step(xw)                               # bottom: lateral, cm
    v = np.ceil(-xw/2 / step) * step
    while v <= xw/2 + 1e-9:
        x = ML + IMG_W * (v + xw/2) / xw
        axis_items.append(cv.create_line(x, MT+IMG_H, x, MT+IMG_H+4, fill=DIM))
        axis_items.append(cv.create_text(x, MT+IMG_H+13, fill=DIM,
                                         font=("Consolas", 9), text=f"{v:g}"))
        v += step
    axis_items.append(cv.create_text(14, MT + IMG_H/2, angle=90, fill=DIM,
        font=("Consolas", 9), text="depth (cm)"))
    axis_items.append(cv.create_text(ML + IMG_W/2, MT + IMG_H + 26, fill=DIM,
        font=("Consolas", 9), text="lateral (cm)"))
    for i in range(N_ELEM):                            # array face on top
        x = ML + IMG_W * (EX[i] + lut["xw"]/2) / lut["xw"]
        if ML <= x <= ML + IMG_W:
            axis_items.append(cv.create_line(x, MT-5, x, MT-1, fill="#4db8ff"))
    axis_items.append(cv.create_rectangle(ML, MT, ML+IMG_W, MT+IMG_H,
                                          outline=FRAME))

def update_wininfo():
    wininfo.config(text=f"win {cfg['samps']} samp | {cfg['win_us']:.0f} us | "
                        f"grid {NX}x{NZ} | {lut['cov']} px in aperture | "
                        f"R {PROBE_R_MM:g} mm  pitch {PITCH_MM:g} mm")

#-------------------------------------------------------------------------------
# render: Hilbert -> gather at LUT delays -> coherent sum -> envelope -> dB
#-------------------------------------------------------------------------------
def render_img():
    with buf_lk:
        samps = cfg["samps"]
        rf = raw_buf.astype(np.float32)
    if lut["idx"] is None or lut["samps"] != samps:
        return                               # LUT rebuild pending after resize
    # analytic signal (Hilbert) per element, at a fast padded FFT length
    X = np.fft.fft(rf, n=lut["nfft"], axis=1)
    X *= lut["wgt"]
    an = np.fft.ifft(X, axis=1)
    pad = lut["an_pad"]                      # (32, samps+1); [:, samps] stays 0
    pad[:, :samps] = an[:, :samps]
    idx = lut["idx"]
    acc = np.zeros(NX * NZ, dtype=np.complex64)
    for i in range(N_ELEM):                  # in-place accumulate: no (32, npix)
        acc += pad[i][idx[i]]                # intermediate, out-of-window and
    mag = np.abs(acc).reshape(NZ, NX)        # out-of-cone hits land on the pad 0

    peak = float(mag.max())
    if peak <= 0.0: peak = 1.0
    db = 20.0 * np.log10(mag / peak + 1e-9)
    dr = float(dyn_db.get())
    v8 = (np.clip((db + gain_db.get() + dr) / dr, 0.0, 1.0)
          * 255.0).astype(np.uint8)
    rgb = np.repeat(v8[..., None], 3, axis=2)          # grayscale B-mode
    big = np.repeat(np.repeat(rgb, SCALE, axis=0), SCALE, axis=1)
    ppm = b"P6\n%d %d\n255\n" % (IMG_W, IMG_H) + big.tobytes()
    ph  = tk.PhotoImage(data=ppm)
    cv.itemconfigure(img_item, image=ph)
    photo_ref[0] = ph
    update_wininfo()

rebuild_lut()
draw_axes()
update_wininfo()

def update():
    if not paused.get() and stats["dirty"]:
        stats["dirty"] = False
        render_img()
    status.config(
        text=f" {stats['mbps']:6.1f} MB/s   {stats['fps']/N_ELEM:6.1f} sweeps/s"
             f"   frames {stats['frames']}   frame drops {stats['drops']}"
             f"   resyncs {stats['resyncs']}"
             + ("" if stats["alive"] else "   *** STREAM STOPPED ***"),
        fg="#7f8" if (stats["drops"] == 0 and stats["resyncs"] == 0) else "#fa5")
    root.after(33, update)                   # full TFM redraw is ~15-20 ms
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
