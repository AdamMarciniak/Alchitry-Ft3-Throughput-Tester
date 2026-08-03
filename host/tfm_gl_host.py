# tfm_gl_host.py
#   python tfm_gl_host.py            -> live GPU TFM B-mode with calipers
#   python tfm_gl_host.py signed     -> treat samples as 12-bit two's complement
#   python tfm_gl_host.py sim        -> no hardware; synthetic phantom (UI testing)
#
# Same acquisition path as tfm_host.py (SRC_SEQ: the FPGA fires elements 0..N-1
# in turn and streams back one TGC-ramped receive window per fire, tagged with
# the element id).  The difference is everything downstream of the USB read:
#
#   tfm_host.py            this file
#   -----------            ---------
#   numpy gather, N x      fragment shader, one thread per screen pixel,
#     (NX*NZ) fancy index    N-element loop in registers
#   np.rint nearest-       hardware bilinear sampling of the analytic signal
#     sample delay index     (fractional delays -> visibly less speckle)
#   fixed 320x256 grid     reconstructs at the window's native pixel size
#   PPM string -> tk       texture -> screen, no CPU copy
#   ~15-20 ms/frame        ~0.2-0.5 ms/frame
#
# The only per-frame CPU work left is the Hilbert transform (N FFTs) and the
# texture upload; the delay LUT is gone entirely, so sound speed, aperture and
# zoom are free live uniforms instead of a tens-of-ms rebuild.
#
# Pipeline, all on the GPU:
#   pass 1  beamform    -> R32F magnitude buffer at the image's pixel size
#   pass 2  max-reduce  -> chain of 2x downsamples down to a 1x1 peak texture
#   pass 3  compress    -> log/dynamic-range/gain -> screen (or a capture FBO)
# Splitting compression out of beamforming means the peak normalisation never
# needs a readback (no pipeline stall), and dyn-range/gain changes while frozen
# only re-run pass 3.
#
# Zoom: wheel zooms about the cursor, middle-drag (or ctrl+drag) pans, double-
# click resets.  Zoom is a shader uniform, so zooming re-beamforms the visible
# region at full screen resolution - it is a real optical zoom into the data,
# not a magnified bitmap.
#
# Calipers: drag on the image to draw a measurement line, drag either end (or
# the middle) to adjust, right-click a line to delete it.  Endpoints are stored
# in metres, so they stay pinned to the tissue through zoom, pan, resize and
# depth/sound-speed changes.
#
# Capture: grabs the current view at CAP_SCALE x the on-screen resolution into
# the side preview and the thumbnail drawer.  Captures keep the measurement
# list as geometry rather than burned-in pixels, so clicking a thumbnail
# reopens it for measuring after the fact.  FREEZE holds the last frame.
#
# Cine loop: the last CINE_SECONDS of acquisition are always in RAM - every
# completed sweep, at whatever rate the FPGA delivers them (no decimation to
# the display rate).  FREEZE stops the recorder and hands the buffer to the
# transport bar under the image: scrub the timeline to go back in time, play
# it forward at 0.1x - 4x, loop it.  What is recorded is the raw int16 RF, not
# pixels, so a replayed frame goes through the same Hilbert + beamformer as a
# live one - zoom, sound speed, dynamic range, gain, calipers and CAPTURE all
# work on the past exactly as they do on the present.
#
# Geometry: convex array, 60 mm radius, 0.5 mm pitch, apex at (0, 0), elements
# pointing radially outward; monostatic (tx == rx), i.e. classic SAFT.
#
# ---------------------------------------------------------------------------
# WIRE FORMAT NOTE (N_ELEM = 48)
# ---------------------------------------------------------------------------
# The 32-element header packed the element id into bits 20:16 and left 23:21
# zero, so a header was identified by (word >> 21) == 0x708.  48 elements need
# 6 bits, which takes bit 21, so the header check here spans bits 31:22
# instead.  ctrl_decode.v / the SRC_SEQ header emitter must widen the element
# field to elem[5:0] (bits 21:16) and keep bits 23:22 zero to match.  Both
# sides are derived from ELEM_BITS below - set it back to 5 and this file
# reproduces the old 32-element contract exactly.
import ctypes as C, sys, time, threading, os, struct, collections
import numpy as np
import moderngl

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import (QSurfaceFormat, QImage, QPixmap, QPainter, QPen,
                           QBrush, QColor, QFont, QFontMetrics, QPolygonF,
                           QShortcut, QKeySequence)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QSlider, QPushButton,
                               QCheckBox, QHBoxLayout, QVBoxLayout, QScrollArea,
                               QFrame, QDialog, QFileDialog, QSizePolicy)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

#===============================================================================
# constants shared with the FPGA
#===============================================================================
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

N_ELEM    = 48
ELEM_BITS = 6                           # bits the element id occupies at 16
ELEM_MASK = (1 << ELEM_BITS) - 1
HDR_SHIFT = 16 + ELEM_BITS              # 22: first bit above the element field
HDR_MAGIC = 0xE1 << (24 - HDR_SHIFT)    # 0x384: top byte 0xE1, guard bits zero
assert N_ELEM <= 1 << ELEM_BITS

C_DEF    = 1540.0           # m/s, soft tissue

PROBE_R_MM   = 60.0         # convex radius of curvature
PITCH_MM     = 0.5          # element pitch along the arc
ACCEPT_DEF   = 30           # element acceptance half-angle, degrees

DEPTH_CM_DEF = 8            # ~104 us window
DLY_US_DEF   = 5            # pulse -> receive settling
GAP_US_DEF   = 50           # receive end -> next pulse (DAC ring-out)
TGC_MIN_DEF, TGC_MAX_DEF = 0, 4095
DYN_DEF, GAIN_DEF = 50, 0

ZOOM_MIN, ZOOM_MAX = 1.0, 24.0

CINE_SECONDS = 20.0         # how far back the loop reaches
CINE_MB      = 1024         # ...and the ceiling on what that is allowed to cost
SPEED_MIN, SPEED_MAX, SPEED_DEF = 0.1, 4.0, 1.0     # replay rate vs acquisition

# |sum of N analytic signals| if every element were rail-to-rail (the Hilbert
# mask doubles the positive spectrum, hence the 2x).  Used as the reference
# when auto-gain is off, so brightness is absolute instead of per-frame.
FULL_SCALE = float(N_ELEM * 2048 * 2)

# element positions/normals, apex of the arc at (0, 0), +z into tissue
_R  = PROBE_R_MM * 1e-3
_th = (np.arange(N_ELEM) - (N_ELEM - 1) / 2.0) * (PITCH_MM / PROBE_R_MM)
EX  = (_R * np.sin(_th)).astype(np.float32)              # lateral, m
EZ  = (_R * (np.cos(_th) - 1.0)).astype(np.float32)      # <= 0: edges curve back
ENX = np.sin(_th).astype(np.float32)                     # outward normals
ENZ = np.cos(_th).astype(np.float32)
ELEM_UNIFORM = np.stack([EX, EZ, ENX, ENZ], axis=1).astype(np.float32)   # (N, 4)
APERTURE_MM  = (N_ELEM - 1) * PITCH_MM

ML, MR, MT, MB = 58, 18, 26, 36     # image margins on screen (axis gutters), px
CAP_SCALE  = 2                      # capture render scale vs on-screen image
THUMB_H    = 92

BG, PLOT_BG, FRAME_C = "#101418", "#0a0e12", "#33505f"
FG, DIM, OK_C, WARN_C = "#9ab", "#5c7080", "#77ff88", "#ffaa55"
MEAS_C, MEAS_HOT = "#ffd24a", "#ff8c3a"

argv = [a.lower() for a in sys.argv[1:]]
mode = {"signed": any(a.startswith("sig") for a in argv)}
FORCE_SIM = any(a.startswith("sim") for a in argv)

#===============================================================================
# window sizing / view state
#===============================================================================
def depth_to_words(cm):
    t = 2.0 * cm / 100.0 / C_DEF               # round trip seconds
    return max(320, min(0xFFFF, int(t * FS_HZ) // 2))

cfg = {}                    # everything derived from the window length
def set_cfg(words):
    samps = 2 * words
    cfg.update(win_words=words, samps=samps, frame_words=words + 1,
               win_us=samps / FS_HZ * 1e6)
set_cfg(depth_to_words(DEPTH_CM_DEF))

# live UI state read by the render thread / shader uniforms
state = {"c": C_DEF, "dly_us": float(DLY_US_DEF), "accept": float(ACCEPT_DEF),
         "dyn": float(DYN_DEF), "gain": float(GAIN_DEF), "auto": True,
         "frozen": False, "depth_cm": DEPTH_CM_DEF}

# visible window into the scene: zoom factor plus the centre it is about
view = {"zoom": 1.0, "cx": 0.0, "cz": None}

def zmax_now():
    """Deepest on-axis echo the current window can hold, in metres."""
    return state["c"] * (state["dly_us"] * 1e-6 + cfg["win_us"] * 1e-6) / 2.0

def reset_view():
    view.update(zoom=1.0, cx=0.0, cz=None)

#===============================================================================
# FT601 bring-up (identical protocol to tfm_host.py)
#===============================================================================
FT_STATUS_NAMES = {
    0: "FT_OK", 1: "FT_INVALID_HANDLE", 2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED", 4: "FT_IO_ERROR", 5: "FT_INSUFFICIENT_RESOURCES",
    6: "FT_INVALID_PARAMETER", 16: "FT_INVALID_ARGS", 17: "FT_NOT_SUPPORTED",
    18: "FT_NO_MORE_ITEMS", 19: "FT_TIMEOUT", 20: "FT_OPERATION_ABORTED",
    21: "FT_RESERVED_PIPE", 22: "FT_INVALID_CONTROL_REQUEST",
}
def ft_status(st): return FT_STATUS_NAMES.get(st, f"0x{st:X}")

class OVERLAPPED(C.Structure):
    _fields_ = [("Internal", C.c_void_p), ("InternalHigh", C.c_void_p),
                ("Pointer",  C.c_void_p), ("hEvent",       C.c_void_p)]

HW, d3, h = False, None, None
if not FORCE_SIM:
    try:
        dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "FTD3XX.dll")
        d3 = C.WinDLL(dll_path)
        d3.FT_Create.restype    = C.c_ulong
        d3.FT_WritePipe.restype = C.c_ulong
        h = C.c_void_p()
        if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX),
                        C.byref(h)) != FT_OK:
            raise OSError("FT_Create failed -- is the Ft+ enumerated?")
        HW = True
    except Exception as e:
        print(f"[no hardware: {e}]")

if not HW:
    print("running in SIMULATION mode - synthetic phantom, no FPGA.")

def send_cmd(word, name=""):
    if not HW:
        return
    buf  = (C.c_ubyte * 4).from_buffer_copy(struct.pack("<I", word & 0xFFFFFFFF))
    sent = C.c_ulong(0)
    st = d3.FT_WritePipe(h, C.c_ubyte(PIPE_OUT), buf, C.c_ulong(4),
                         C.byref(sent), None)
    if st != FT_OK or sent.value != 4:
        sys.exit(f"control write failed ({name}): "
                 f"st={st} ({ft_status(st)}) sent={sent.value}")

def cmd(op, payload=0):
    return ((op & 0xFF) << 24) | (payload & 0xFFFFFF)

def us_to_cycles(us): return int(us) * (CLK_HZ // 1_000_000)

def send_seq_config(lo, hi, dly_us, gap_us):
    """Push the full sequencer timing/TGC setup for the current window length."""
    inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
    send_cmd(cmd(OP_SEQ_LEN, cfg["win_words"]), "seq_len")
    send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(dly_us)), "seq_dly")
    send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(gap_us)), "seq_gap")
    send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
    send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

bufs = views = ovs = got = None
if HW:
    d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))
    print("locking RX window (0xA5A55A5A)...")
    send_cmd(LOCK_WORD, "lock")
    time.sleep(0.05)
    send_cmd(cmd(OP_RST_CNT), "rst_cnt")    # implies STOP, zeroes word count
    send_cmd(cmd(OP_SET_SRC, SRC_SEQ), "set_src")
    send_seq_config(TGC_MIN_DEF, TGC_MAX_DEF, DLY_US_DEF, GAP_US_DEF)

    d3.FT_SetStreamPipe(h, C.c_int(0), C.c_int(0),
                        C.c_ubyte(PIPE_IN), C.c_ulong(XFER))
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
    send_cmd(cmd(OP_START), "start")        # ring armed first, THEN start

#===============================================================================
# shared state: reader thread <-> render
#===============================================================================
buf_lk  = threading.Lock()
raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  # full-res windows
carry   = np.empty(0, dtype=np.uint32)

stats = {"bytes": 0, "win_bytes": 0, "t0": time.perf_counter(), "mbps": 0.0,
         "frames": 0, "win_frames": 0, "fps": 0.0, "drops": 0, "resyncs": 0,
         "last_fcnt": None, "alive": True, "dirty": False}
perf  = {"gpu_ms": 0.0, "cpu_ms": 0.0, "hil_ms": 0.0}

# Hilbert hand-off: the worker publishes a whole new array each time, so the
# GL thread can grab the reference under the lock and upload it outside.
hil_lk = threading.Lock()
hil_ev = threading.Event()
hil    = {"data": None, "samps": 0, "gen": 0}

# A replay frame jumps the queue: the worker renders it instead of the live
# buffer, so scrubbing the cine loop still gets its FFTs off the UI thread.
replay_lk = threading.Lock()
replay    = {"rf": None}

def request_replay(rf):
    """Ask the Hilbert worker to publish this recorded sweep (int16 (N, samps))."""
    with replay_lk:
        replay["rf"] = rf
    hil_ev.set()

#===============================================================================
# cine loop: rolling recording of the raw RF, one entry per completed sweep
#===============================================================================
class Cine:
    """Ring of int16 RF windows, bounded by both age (CINE_SECONDS) and size
    (CINE_MB).  Slots are recycled off the tail rather than reallocated, so a
    push is one memcpy and the steady state makes no garbage.

    Storing RF instead of pixels costs ~400 kB/sweep at 8 cm depth (~50 MB/s at
    130 sweeps/s), which is what buys a replayed frame the full pipeline: it is
    re-beamformed on demand, so zoom/gain/c/calipers stay live while frozen."""
    def __init__(self):
        self.lk   = threading.Lock()
        self.buf  = collections.deque()     # (t_perf, (N, samps) int16), oldest first
        self.free = []                      # slots recycled off the tail
        self.shape, self.cap, self.fbytes = None, 1, 0
        self.recording = True

    def _configure(self, shape):
        self.shape  = tuple(shape)
        self.fbytes = int(np.prod(shape)) * 2
        self.cap    = max(8, int(CINE_MB * 1024 * 1024 // self.fbytes))

    def reset(self):
        with self.lk:
            self.buf.clear()
            self.free.clear()
            self.shape = None

    def push(self, src):
        """One completed sweep.  Called from the reader thread with buf_lk held,
        so it has to stay cheap - one ~0.1 ms copy into a recycled slot."""
        if not self.recording:
            return
        t = time.perf_counter()
        with self.lk:
            if self.shape != tuple(src.shape):      # depth changed under us
                self.buf.clear(); self.free.clear()
                self._configure(src.shape)
            while self.buf and (len(self.buf) >= self.cap or
                                t - self.buf[0][0] > CINE_SECONDS):
                self.free.append(self.buf.popleft()[1])
            a = self.free.pop() if self.free else np.empty(self.shape, np.int16)
            np.copyto(a, src)
            self.buf.append((t, a))

    def status(self):
        """(frames, seconds held, MB resident) for the readout."""
        with self.lk:
            n    = len(self.buf)
            secs = (self.buf[-1][0] - self.buf[0][0]) if n > 1 else 0.0
            mb   = (n + len(self.free)) * self.fbytes / 1e6
        return n, secs, mb

    def freeze(self):
        """Stop recording and hand out a stable, O(1)-indexable snapshot.  With
        the recorder off, nothing recycles the slots the snapshot points at."""
        self.recording = False
        with self.lk:
            items = list(self.buf)
        if not items:
            return [], np.zeros(0)
        t0 = items[0][0]
        return items, np.array([t - t0 for t, _ in items], dtype=np.float64)

    def resume(self):
        self.recording = True

cine = Cine()
_prev_elem = -1             # last element id seen, for sweep-boundary detection

def batch(fr):
    """fr: (m, frame_words) uint32, all rows verified to start with a header."""
    global _prev_elem
    hdr   = fr[:, 0]
    elems = ((hdr >> 16) & ELEM_MASK).astype(np.int32)
    fcnt  = (hdr & 0xFFFF).astype(np.int64)
    if stats["last_fcnt"] is not None and \
       ((int(fcnt[0]) - stats["last_fcnt"]) & 0xFFFF) != 1:
        stats["drops"] += 1
    stats["drops"] += int(np.count_nonzero((np.diff(fcnt) & 0xFFFF) != 1))
    stats["last_fcnt"] = int(fcnt[-1])

    u = (np.ascontiguousarray(fr[:, 1:]).view(np.uint16) & 0x0FFF).astype(np.int32)
    c = np.where(u >= 2048, u - 4096, u) if mode["signed"] else u - 2048
    c = c.astype(np.int16)
    keep = elems < N_ELEM                   # ignore ids the array cannot hold

    # raw_buf is written in place, so the only instant it holds one coherent
    # sweep is just before the element id wraps.  Split the chunk there and
    # snapshot in the gaps - that records every sweep, at the acquisition rate,
    # rather than whatever the display happened to sample.  A chunk spans ~2-3
    # sweeps at 8 cm, so this loop runs a couple of times per 1 MB transfer.
    wraps = np.nonzero(np.diff(np.concatenate(([_prev_elem], elems))) < 0)[0]
    lo = 0
    for w in wraps:
        w = int(w)
        k = keep[lo:w]
        raw_buf[elems[lo:w][k]] = c[lo:w][k]
        cine.push(raw_buf)
        lo = w
    k = keep[lo:]
    raw_buf[elems[lo:][k]] = c[lo:][k]
    _prev_elem = int(elems[-1])

    stats["frames"]     += fr.shape[0]
    stats["win_frames"] += fr.shape[0]
    stats["dirty"] = True
    hil_ev.set()

def process(words):
    """Frame parser.  Fast path: back-to-back aligned frames, fully vectorized.
    A header is 0xE1 in the top byte with the guard bits above the element
    field zero -> (word >> HDR_SHIFT) == HDR_MAGIC."""
    global carry
    with buf_lk:
        FW = cfg["frame_words"]
        w = np.concatenate((carry, words)) if carry.size else words
        pos, n = 0, w.size
        while n - pos >= FW:
            nfr  = (n - pos) // FW
            hdrs = w[pos : pos + nfr*FW : FW]
            ok   = (hdrs >> HDR_SHIFT) == HDR_MAGIC
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
                    nxt = np.nonzero((w[pos+1:] >> HDR_SHIFT) == HDR_MAGIC)[0]
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

def sim_reader():
    """Synthetic phantom so the UI can be exercised without the FPGA: a handful
    of point scatterers plus noise, re-rendered at ~30 sweeps/s."""
    scat = [(0.000, 0.020), (0.010, 0.034), (-0.013, 0.048),
            (0.005, 0.062), (-0.004, 0.013), (0.017, 0.075)]
    while stats["alive"]:
        with buf_lk:
            samps, c = cfg["samps"], state["c"]
        t = (np.arange(samps, dtype=np.float32) / FS_HZ)[None, :]
        a = np.zeros((N_ELEM, samps), np.float32)
        dly_s = state["dly_us"] * 1e-6
        for (sx, sz) in scat:
            d   = np.hypot(sx - EX, sz - EZ).astype(np.float32)
            tof = (2.0 * d / c - dly_s)[:, None]
            dt  = t - tof
            a  += 900.0 * np.exp(-(dt / 2.5e-7) ** 2) * np.cos(2*np.pi*5e6 * dt)
        a += np.random.normal(0.0, 35.0, a.shape).astype(np.float32)
        with buf_lk:
            if cfg["samps"] == samps:
                raw_buf[:] = np.clip(a, -2048, 2047).astype(np.int16)
                cine.push(raw_buf)          # one synthetic sweep == one frame
                stats["dirty"] = True
                hil_ev.set()
                stats["frames"] += N_ELEM
                stats["win_frames"] += N_ELEM
                stats["bytes"] += samps * 2 * N_ELEM
                stats["win_bytes"] += samps * 2 * N_ELEM
        dt_w = time.perf_counter() - stats["t0"]
        if dt_w >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt_w / 1e6
            stats["fps"]  = stats["win_frames"] / dt_w
            stats["win_bytes"], stats["win_frames"] = 0, 0
            stats["t0"] = time.perf_counter()
        time.sleep(1.0 / 30.0)

threading.Thread(target=reader if HW else sim_reader, daemon=True).start()

def hilbert_worker():
    """The analytic-signal transform is the only CPU-heavy step left (~6 ms for
    48 elements with numpy).  Run it here rather than in paintGL so it never
    stalls the UI, and not in the reader thread so it never delays requeueing a
    USB buffer.  Publishes a fresh array per sweep; the GL thread just uploads
    whatever generation it finds.

    Replay requests pre-empt the live buffer, so scrubbing the cine loop runs
    through exactly the same transform - and off the UI thread as well."""
    while stats["alive"]:
        hil_ev.wait(0.1)
        hil_ev.clear()
        if not stats["alive"]:
            return
        with replay_lk:
            rep = replay["rf"]
            replay["rf"] = None
        if rep is not None:
            samps = rep.shape[1]
            t0 = time.perf_counter()
            out = analytic(rep.astype(np.float32), samps)
            perf["hil_ms"] = (time.perf_counter() - t0) * 1e3
            with hil_lk:
                hil.update(data=out, samps=samps, gen=hil["gen"] + 1)
            continue
        if state["frozen"]:
            continue                    # frozen: nothing will look at the result
        with buf_lk:
            if not stats["dirty"]:
                continue
            stats["dirty"] = False
            samps = cfg["samps"]
            rf = raw_buf.astype(np.float32)
        t0 = time.perf_counter()
        out = analytic(rf, samps)
        perf["hil_ms"] = (time.perf_counter() - t0) * 1e3
        if state["frozen"]:             # froze mid-transform: do not stomp the
            continue                    # frame the user just paused on
        with hil_lk:
            hil.update(data=out, samps=samps, gen=hil["gen"] + 1)
# started below, once analytic() exists

#===============================================================================
# analytic signal (the one piece of per-frame CPU work left)
#===============================================================================
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

try:                        # optional: ~2x faster here, because scipy keeps
    from scipy.fft import fft as _fft, ifft as _ifft      # float32 -> complex64
    _FFT_KW = {"workers": -1}                             # while numpy always
    FFT_LIB = "scipy"                                     # promotes to float64
except ImportError:
    _fft, _ifft, _FFT_KW, FFT_LIB = np.fft.fft, np.fft.ifft, {}, "numpy"

_hilb = {"nfft": 0, "wgt": None}
def analytic(rf, samps):
    """(N, samps) real -> (N, samps, 2) float32 interleaved re/im.

    The only per-frame CPU work in the whole pipeline (~6 ms for 48 elements
    with numpy, ~3 ms with scipy installed).  Everything else is on the GPU."""
    if _hilb["nfft"] != next_fast_len(samps):
        nfft = next_fast_len(samps)
        wgt  = np.zeros(nfft, dtype=np.float32)     # Hilbert spectrum mask
        wgt[0] = 1.0; wgt[nfft//2] = 1.0; wgt[1:nfft//2] = 2.0
        _hilb.update(nfft=nfft, wgt=wgt)
    X = _fft(rf, n=_hilb["nfft"], axis=1, **_FFT_KW)
    X *= _hilb["wgt"]
    an = _ifft(X, axis=1, **_FFT_KW)[:, :samps]
    out = np.empty((N_ELEM, samps, 2), dtype=np.float32)
    out[..., 0] = an.real
    out[..., 1] = an.imag
    return out

threading.Thread(target=hilbert_worker, daemon=True).start()

#===============================================================================
# shaders
#===============================================================================
VERT = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

# One thread per output pixel; the element loop lives in registers and every
# A-scan fetch is a hardware bilinear tap, so the delay is applied at fractional
# sample resolution instead of being rounded to the nearest sample.
# `viewbox` is the visible slab of tissue (x0, x1, z0, z1) in metres - zooming
# just narrows it, so the reconstruction always fills the screen's real pixels.
BEAMFORM = """
#version 330
in vec2 v_uv;
out float f_mag;

uniform sampler2D rf;          // RG32F, width = samps, height = N (re, im)
uniform vec4  elems[%(N)d];    // (x, z, nx, nz): position m, outward normal
uniform vec4  viewbox;         // x0, x1, z0, z1 in metres
uniform float c, dly_s, fs;    // sound speed m/s, pulse->rx delay s, sample rate
uniform float samps;           // valid samples per A-scan == texture width
uniform float cos_acc;         // cos(acceptance half-angle)

void main() {
    vec2 p = vec2(mix(viewbox.x, viewbox.y, v_uv.x),
                  mix(viewbox.z, viewbox.w, 1.0 - v_uv.y));
    vec2 acc = vec2(0.0);
    float inv_w = 1.0 / samps;
    for (int i = 0; i < %(N)d; i++) {
        vec2 dv = p - elems[i].xy;
        float d = length(dv);
        // tx == rx (monostatic): round trip is 2*d; capture starts dly_s after fire
        float t = (2.0 * d / c - dly_s) * fs;
        float cosa = dot(dv, elems[i].zw) / max(d, 1e-9);
        if (t >= 0.0 && t <= samps - 1.0 && cosa >= cos_acc) {
            acc += texture(rf, vec2((t + 0.5) * inv_w,
                                    (float(i) + 0.5) / %(N)d.0)).rg;
        }
    }
    f_mag = length(acc);        // envelope of the coherent sum
}
""" % {"N": N_ELEM}

# 2x2 max downsample.  Chained to 1x1 so the display pass can read the frame
# peak straight out of a texture - no glReadPixels, no pipeline stall.
REDUCE = """
#version 330
out float f_max;
uniform sampler2D src;
uniform ivec2 srcsz;
void main() {
    ivec2 b = ivec2(gl_FragCoord.xy) * 2;
    float m = 0.0;
    for (int dy = 0; dy < 2; dy++)
        for (int dx = 0; dx < 2; dx++)
            m = max(m, texelFetch(src, min(b + ivec2(dx, dy), srcsz - 1), 0).r);
    f_max = m;
}
"""

COMPRESS = """
#version 330
in vec2 v_uv;
out vec4 f_color;
uniform sampler2D magtex;
uniform sampler2D maxtex;      // 1x1, frame peak
uniform float dyn_db, gain_db, full_scale, auto_gain;
void main() {
    float mag  = texture(magtex, v_uv).r;
    float peak = mix(full_scale, max(texelFetch(maxtex, ivec2(0, 0), 0).r, 1e-9),
                     auto_gain);
    float db = 20.0 * log(mag / peak + 1e-9) / log(10.0);
    float v  = clamp((db + gain_db + dyn_db) / dyn_db, 0.0, 1.0);
    f_color  = vec4(v, v, v, 1.0);
}
"""

#===============================================================================
# GL widget: the B-mode image itself, nothing else
#===============================================================================
class BModeGL(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = None
        self.mag_fbo = self.mag_tex = None
        self.reduce = []            # [(fbo, tex, (w, h), (srcw, srch))]
        self.rf_tex = None
        self.tex_samps = 0
        self.tex_gen = -1
        self.fb_w = self.fb_h = 1
        self._screen = None
        self._screen_id = -1
        self._q = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(240, 200)

    # -- setup ----------------------------------------------------------------
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.prog_bf = self.ctx.program(vertex_shader=VERT, fragment_shader=BEAMFORM)
        self.prog_rd = self.ctx.program(vertex_shader=VERT, fragment_shader=REDUCE)
        self.prog_cp = self.ctx.program(vertex_shader=VERT, fragment_shader=COMPRESS)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.vao_bf = self.ctx.vertex_array(self.prog_bf, [(self.vbo, '2f', 'in_pos')])
        self.vao_rd = self.ctx.vertex_array(self.prog_rd, [(self.vbo, '2f', 'in_pos')])
        self.vao_cp = self.ctx.vertex_array(self.prog_cp, [(self.vbo, '2f', 'in_pos')])
        self.prog_bf['elems'].write(ELEM_UNIFORM.tobytes())
        self.prog_bf['rf'].value = 0
        self.prog_cp['magtex'].value = 0
        self.prog_cp['maxtex'].value = 1
        self.prog_cp['full_scale'].value = FULL_SCALE

    def _release(self, objs):
        for o in objs:
            try: o.release()
            except Exception: pass

    def _alloc_targets(self, w, h):
        """(Re)build the magnitude buffer and its max-reduction chain."""
        old = [self.mag_fbo, self.mag_tex]
        for fbo, tex, _, _ in self.reduce:
            old += [fbo, tex]
        self.reduce = []
        self.mag_tex = self.ctx.texture((w, h), 1, dtype='f4')
        self.mag_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.mag_tex.repeat_x = self.mag_tex.repeat_y = False
        self.mag_fbo = self.ctx.framebuffer(color_attachments=[self.mag_tex])
        sw, sh = w, h
        while sw > 1 or sh > 1:
            dw, dh = max(1, (sw + 1)//2), max(1, (sh + 1)//2)
            tex = self.ctx.texture((dw, dh), 1, dtype='f4')
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            self.reduce.append((fbo, tex, (dw, dh), (sw, sh)))
            sw, sh = dw, dh
        self._release([o for o in old if o is not None])

    def resizeGL(self, w, h):
        self.fb_w, self.fb_h = max(1, w), max(1, h)
        self._alloc_targets(self.fb_w, self.fb_h)
        self._screen_id = -1

    # -- the visible slab of tissue ------------------------------------------
    def full_extent(self):
        """(xw, zmax) in metres covering the whole window, at square pixels."""
        zmax = zmax_now()
        return zmax * (self.fb_w / max(1, self.fb_h)), zmax

    def view_box(self):
        """Visible (x0, x1, z0, z1) in metres, clamped inside the full extent.
        Also writes the clamped centre back so panning stops at the edges."""
        xw, zmax = self.full_extent()
        z = min(max(view["zoom"], ZOOM_MIN), ZOOM_MAX)
        w, hgt = xw / z, zmax / z
        cz = view["cz"] if view["cz"] is not None else zmax / 2.0
        cx = min(max(view["cx"], -xw/2 + w/2), xw/2 - w/2)
        cz = min(max(cz, hgt/2), zmax - hgt/2)
        view.update(zoom=z, cx=cx, cz=cz)
        return (cx - w/2, cx + w/2, cz - hgt/2, cz + hgt/2)

    # -- per-frame ------------------------------------------------------------
    def _reset_state(self):
        """QOpenGLWidget hands us the context with its own compositing state
        still set - notably GL_BLEND, which silently eats everything we render
        into the float buffers.  Reset before every batch of passes."""
        self.ctx.enable_only(moderngl.NOTHING)

    def _upload(self):
        """Take whatever the Hilbert worker last published.  Nothing but a
        memcpy to the GPU happens on this thread."""
        with hil_lk:
            if hil["data"] is None or hil["gen"] == self.tex_gen:
                return
            data, samps, gen = hil["data"], hil["samps"], hil["gen"]
        if self.tex_samps != samps or self.rf_tex is None:
            if self.rf_tex is not None:
                self._release([self.rf_tex])
            self.rf_tex = self.ctx.texture((samps, N_ELEM), 2, dtype='f4')
            # LINEAR gives the fractional-delay interpolation; sampling exactly at
            # (i + 0.5)/N in y hits a texel centre, so rows never bleed together
            self.rf_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.rf_tex.repeat_x = self.rf_tex.repeat_y = False
            self.tex_samps = samps
        self.rf_tex.write(data)
        self.tex_gen = gen

    def _beamform(self, fbo, size, vb):
        p = self.prog_bf
        p['viewbox'].value = (float(vb[0]), float(vb[1]),
                              float(vb[2]), float(vb[3]))
        p['c'].value       = float(state["c"])
        p['dly_s'].value   = float(state["dly_us"]) * 1e-6
        p['fs'].value      = float(FS_HZ)
        p['samps'].value   = float(self.tex_samps)
        p['cos_acc'].value = float(np.cos(np.radians(state["accept"])))
        self.rf_tex.use(0)
        fbo.use()
        fbo.viewport = (0, 0, size[0], size[1])
        self.vao_bf.render(moderngl.TRIANGLE_STRIP)

    def _run_reduce(self):
        src = self.mag_tex
        for fbo, tex, (dw, dh), (sw, sh) in self.reduce:
            src.use(0)
            self.prog_rd['src'].value = 0
            self.prog_rd['srcsz'].value = (sw, sh)
            fbo.use()
            fbo.viewport = (0, 0, dw, dh)
            self.vao_rd.render(moderngl.TRIANGLE_STRIP)
            src = tex

    def _compress(self, magtex, fbo, size):
        magtex.use(0)
        (self.reduce[-1][1] if self.reduce else magtex).use(1)
        self.prog_cp['dyn_db'].value    = float(state["dyn"])
        self.prog_cp['gain_db'].value   = float(state["gain"])
        self.prog_cp['auto_gain'].value = 1.0 if state["auto"] else 0.0
        fbo.use()
        fbo.viewport = (0, 0, size[0], size[1])
        self.vao_cp.render(moderngl.TRIANGLE_STRIP)

    def paintGL(self):
        if self.ctx is None or self.mag_fbo is None:
            return
        t0 = time.perf_counter()
        # Always take the newest published generation: while frozen the worker
        # only publishes replay frames, so this is what makes scrubbing work.
        self._upload()
        if self.rf_tex is None:
            return
        self._reset_state()
        vb = self.view_box()
        q = None
        if self._q % 30 == 0:
            q = self.ctx.query(time=True)
            q.__enter__()
        self._beamform(self.mag_fbo, (self.fb_w, self.fb_h), vb)
        self._run_reduce()
        fid = self.defaultFramebufferObject()
        if fid != self._screen_id:
            self._screen = self.ctx.detect_framebuffer(fid)
            self._screen_id = fid
        self._compress(self.mag_tex, self._screen, (self.fb_w, self.fb_h))
        if q is not None:
            q.__exit__(None, None, None)
            perf["gpu_ms"] = q.elapsed / 1e6
        self._q += 1
        perf["cpu_ms"] = (time.perf_counter() - t0) * 1e3

    # -- capture --------------------------------------------------------------
    def grab_bmode(self, scale=CAP_SCALE):
        """Re-render the current view at `scale` x resolution into an offscreen
        FBO and read it back as a QImage.  Same uniforms, so it is exactly the
        on-screen image - including the zoom - just sampled on a finer grid."""
        if self.ctx is None or self.rf_tex is None:
            return None, None
        self.makeCurrent()
        self._reset_state()
        w, h = int(self.fb_w * scale), int(self.fb_h * scale)
        vb = self.view_box()
        mag_t = self.ctx.texture((w, h), 1, dtype='f4')
        mag_t.filter = (moderngl.NEAREST, moderngl.NEAREST)
        mag_f = self.ctx.framebuffer(color_attachments=[mag_t])
        rgb_t = self.ctx.texture((w, h), 4)
        rgb_f = self.ctx.framebuffer(color_attachments=[rgb_t])
        try:
            self._beamform(mag_f, (w, h), vb)
            self._compress(mag_t, rgb_f, (w, h))    # peak from the live chain
            raw = rgb_f.read(components=3, alignment=1)
        finally:
            self._release([mag_f, mag_t, rgb_f, rgb_t])
            self.doneCurrent()
        a = np.frombuffer(raw, np.uint8).reshape(h, w, 3)[::-1]   # GL is bottom-up
        a = np.ascontiguousarray(a)
        return QImage(a.data, w, h, 3*w, QImage.Format_RGB888).copy(), vb

#===============================================================================
# scene painting shared by the live overlay and the captures
#===============================================================================
def sc2px(vb, r, x, z):
    return QPointF(r.left() + (x - vb[0]) / (vb[1] - vb[0]) * r.width(),
                   r.top()  + (z - vb[2]) / (vb[3] - vb[2]) * r.height())

def px2sc(vb, r, px, py):
    if r.width() <= 0 or r.height() <= 0:
        return 0.0, 0.0
    return (vb[0] + (px - r.left()) / r.width()  * (vb[1] - vb[0]),
            vb[2] + (py - r.top())  / r.height() * (vb[3] - vb[2]))

def nice_step(rng):
    for s in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if rng / s <= 10: return s
    return 100

def paint_axes(p, r, vb, s=1.0):
    """Depth (cm) down the left, lateral (cm) along the bottom, array face on
    top.  Ticks follow the visible range, so they get finer as you zoom in."""
    p.save()
    p.setFont(QFont("Consolas", max(6, int(9 * s))))
    fm = QFontMetrics(p.font())
    p.setPen(QPen(QColor(DIM), max(1.0, s)))
    x0, x1, z0, z1 = [v * 100.0 for v in vb]        # cm

    step = nice_step(z1 - z0)                       # left: depth
    v = np.ceil(z0 / step) * step
    while v <= z1 + 1e-9:
        y = r.top() + r.height() * (v - z0) / (z1 - z0)
        p.drawLine(QPointF(r.left() - 5*s, y), QPointF(r.left(), y))
        t = f"{v:g}"
        p.drawText(QPointF(r.left() - 8*s - fm.horizontalAdvance(t),
                           y + fm.ascent()/2 - 1), t)
        v += step
    step = nice_step(x1 - x0)                       # bottom: lateral
    v = np.ceil(x0 / step) * step
    while v <= x1 + 1e-9:
        x = r.left() + r.width() * (v - x0) / (x1 - x0)
        p.drawLine(QPointF(x, r.bottom()), QPointF(x, r.bottom() + 5*s))
        t = f"{v:g}"
        p.drawText(QPointF(x - fm.horizontalAdvance(t)/2,
                           r.bottom() + 7*s + fm.ascent()), t)
        v += step

    p.save()
    p.translate(QPointF(r.left() - 40*s, r.center().y()))
    p.rotate(-90)
    p.drawText(QPointF(-fm.horizontalAdvance("depth (cm)")/2, 0), "depth (cm)")
    p.restore()
    p.drawText(QPointF(r.center().x() - fm.horizontalAdvance("lateral (cm)")/2,
                       r.bottom() + 7*s + 2.2*fm.ascent()), "lateral (cm)")

    if vb[2] <= 0.002:                  # only meaningful when the face is in view
        p.setPen(QPen(QColor("#4db8ff"), max(1.0, s)))
        for i in range(N_ELEM):
            x = sc2px(vb, r, EX[i], 0.0).x()
            if r.left() <= x <= r.right():
                p.drawLine(QPointF(x, r.top() - 6*s), QPointF(x, r.top() - 1*s))
    p.setPen(QPen(QColor(FRAME_C), max(1.0, s)))
    p.drawRect(r)
    p.restore()

def meas_mm(m):
    return float(np.hypot(m[2] - m[0], m[3] - m[1]) * 1000.0)

def paint_measures(p, r, vb, measures, s=1.0, hot=None):
    """Calipers: cross at each end, line between, distance label at the midpoint."""
    if not measures:
        return
    p.save()
    p.setClipRect(r)            # a caliper dragged out of view must not spill
                                # over the toolbar / axis gutters
    p.setRenderHint(QPainter.Antialiasing, True)
    font = QFont("Consolas", max(7, int(10 * s)))
    font.setBold(True)
    p.setFont(font)
    fm = QFontMetrics(font)
    arm, hr = 7.0 * s, 4.5 * s

    for i, m in enumerate(measures):
        col = QColor(MEAS_HOT if hot == i else MEAS_C)
        a, b = sc2px(vb, r, m[0], m[1]), sc2px(vb, r, m[2], m[3])
        p.setPen(QPen(QColor(0, 0, 0, 150), 3.0 * s))
        p.drawLine(a, b)
        p.setPen(QPen(col, 1.4 * s))
        p.drawLine(a, b)
        for q in (a, b):
            p.drawLine(QPointF(q.x() - arm, q.y()), QPointF(q.x() + arm, q.y()))
            p.drawLine(QPointF(q.x(), q.y() - arm), QPointF(q.x(), q.y() + arm))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(q, hr, hr)

        txt = f"{meas_mm(m):.1f} mm"
        mid = QPointF((a.x() + b.x())/2, (a.y() + b.y())/2)
        tw, th = fm.horizontalAdvance(txt), fm.height()
        box = QRectF(mid.x() + 8*s, mid.y() - th/2 - 2*s, tw + 8*s, th + 4*s)
        if box.right() > r.right():
            box.moveLeft(mid.x() - 8*s - box.width())
        box.moveLeft(min(max(box.left(), r.left() + 2*s),
                         r.right() - box.width() - 2*s))
        box.moveTop(min(max(box.top(), r.top() + 2*s),
                        r.bottom() - box.height() - 2*s))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 170)))
        p.drawRoundedRect(box, 3*s, 3*s)
        p.setPen(QPen(col))
        p.drawText(QPointF(box.left() + 4*s, box.top() + 2*s + fm.ascent()), txt)
    p.restore()

#===============================================================================
# measurement interaction, shared by the live overlay and the capture viewer
#===============================================================================
HIT = 10.0          # grab radius, px

def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L = dx*dx + dy*dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px-x0)*dx + (py-y0)*dy) / L))
    return np.hypot(px - (x0 + t*dx), py - (y0 + t*dy))

class MeasureCanvas(QWidget):
    """Mouse handling for calipers.  Subclasses supply image_rect() and the
    view box; endpoints are kept in metres so they survive zoom, pan, resize,
    depth changes and being re-rendered into a capture at another resolution."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.measures = []          # [x0, z0, x1, z1] in metres
        self.vb = (-0.05, 0.05, 0.0, 0.08)
        self._drag = None           # (index, which)  which: 0, 1 or 2 (=whole line)
        self._off = None
        self._new = False
        self.hot = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def image_rect(self):
        raise NotImplementedError

    def _pick(self, pt):
        """-> (index, which) for the nearest grabbable thing, or None."""
        r = self.image_rect()
        best = None
        for i, m in enumerate(self.measures):
            for w, (x, z) in enumerate(((m[0], m[1]), (m[2], m[3]))):
                q = sc2px(self.vb, r, x, z)
                d = np.hypot(pt.x() - q.x(), pt.y() - q.y())
                if d <= HIT and (best is None or d < best[0]):
                    best = (d, i, w)
        if best:
            return best[1], best[2]
        for i, m in enumerate(self.measures):
            a = sc2px(self.vb, r, m[0], m[1])
            b = sc2px(self.vb, r, m[2], m[3])
            if seg_dist(pt.x(), pt.y(), a.x(), a.y(), b.x(), b.y()) <= HIT:
                return i, 2
        return None

    # -- events ---------------------------------------------------------------
    def mousePressEvent(self, ev):
        pt = ev.position()
        hit = self._pick(pt)
        if ev.button() == Qt.RightButton:
            if hit:
                self.measures.pop(hit[0])
                self.hot = None
                self.update(); self.changed.emit()
            return
        if ev.button() != Qt.LeftButton:
            return
        if not self.image_rect().contains(pt) and not hit:
            return
        if hit:
            i, w = hit
            self._drag, self._new = (i, w), False
            if w == 2:
                x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
                m = self.measures[i]
                self._off = (m[0]-x, m[1]-z, m[2]-x, m[3]-z)
        else:
            x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
            self.measures.append([x, z, x, z])
            self._drag, self._new = (len(self.measures)-1, 1), True
        self.hot = self._drag[0]
        self.update(); self.changed.emit()

    def mouseMoveEvent(self, ev):
        pt = ev.position()
        if self._drag is None:
            hit = self._pick(pt)
            hot = hit[0] if hit else None
            self.setCursor(Qt.SizeAllCursor if hit and hit[1] == 2 else
                           (Qt.PointingHandCursor if hit else Qt.CrossCursor))
            if hot != self.hot:
                self.hot = hot
                self.update()
            return
        i, w = self._drag
        x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
        m = self.measures[i]
        if w == 2:
            m[0], m[1] = x + self._off[0], z + self._off[1]
            m[2], m[3] = x + self._off[2], z + self._off[3]
        else:
            m[2*w], m[2*w+1] = x, z
        self.update(); self.changed.emit()

    def mouseReleaseEvent(self, ev):
        if self._drag is None:
            return
        i, _ = self._drag
        m = self.measures[i]
        r = self.image_rect()
        a, b = sc2px(self.vb, r, m[0], m[1]), sc2px(self.vb, r, m[2], m[3])
        if self._new and np.hypot(a.x()-b.x(), a.y()-b.y()) < 4.0:
            self.measures.pop(i)            # a plain click, not a drag
            self.hot = None
        self._drag, self._new = None, False
        self.update(); self.changed.emit()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.measures:
            self.measures.pop(self.hot if self.hot is not None else -1)
            self.hot = None
            self.update(); self.changed.emit()
        else:
            super().keyPressEvent(ev)

    def clear_measures(self):
        self.measures.clear()
        self.hot = None
        self.update(); self.changed.emit()

#===============================================================================
# live scene: GL image + transparent overlay for axes, calipers and zoom
#===============================================================================
class LiveOverlay(MeasureCanvas):
    """Transparent child sitting on the GL widget.  Owns zoom/pan because it is
    the thing receiving the mouse; the GL widget reads the resulting view box."""
    zoomed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pan = None

    def image_rect(self):
        return QRectF(ML, MT, max(1, self.width() - ML - MR),
                      max(1, self.height() - MT - MB))

    # -- zoom / pan -----------------------------------------------------------
    def wheelEvent(self, ev):
        r = self.image_rect()
        pt = ev.position()
        if not r.contains(pt):
            return
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        old = view["zoom"]
        new = min(max(old * (1.25 ** steps), ZOOM_MIN), ZOOM_MAX)
        if new == old:
            return
        # keep the tissue under the cursor pinned while the box shrinks/grows
        x, z = px2sc(self.vb, r, pt.x(), pt.y())
        fx = (pt.x() - r.left()) / r.width()
        fy = (pt.y() - r.top()) / r.height()
        w  = (self.vb[1] - self.vb[0]) * old / new
        hg = (self.vb[3] - self.vb[2]) * old / new
        view.update(zoom=new, cx=x - (fx - 0.5) * w, cz=z - (fy - 0.5) * hg)
        self.zoomed.emit()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or \
           (ev.button() == Qt.LeftButton and ev.modifiers() & Qt.ControlModifier):
            self._pan = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._pan is not None:
            r = self.image_rect()
            x0, z0 = px2sc(self.vb, r, self._pan.x(), self._pan.y())
            x1, z1 = px2sc(self.vb, r, ev.position().x(), ev.position().y())
            view["cx"] += x0 - x1
            view["cz"] = (view["cz"] or 0.0) + z0 - z1
            self._pan = ev.position()
            self.zoomed.emit()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.CrossCursor)
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self._pick(ev.position()):
            reset_view()
            self.zoomed.emit()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.image_rect()
        paint_axes(p, r, self.vb, 1.0)
        paint_measures(p, r, self.vb, self.measures, 1.0, self.hot)
        p.end()

class Scene(QWidget):
    """Container: paints the background, sizes the GL widget inside the axis
    gutters, and keeps a transparent overlay on top of it."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"background:{PLOT_BG};")
        self.gl = BModeGL(self)
        self.ov = LiveOverlay(self)
        self.ov.raise_()
        self.ov.zoomed.connect(self.gl.update)
        self.setMinimumSize(420, 340)

    def resizeEvent(self, ev):
        w, h = self.width(), self.height()
        self.gl.setGeometry(ML, MT, max(1, w - ML - MR), max(1, h - MT - MB))
        self.ov.setGeometry(0, 0, w, h)

    def sync_view(self):
        self.ov.vb = self.gl.view_box()

#===============================================================================
# captures
#===============================================================================
class Capture:
    _n = 0
    def __init__(self, img, vb, measures, info):
        Capture._n += 1
        self.n = Capture._n
        self.img, self.vb = img, vb
        self.measures = [list(m) for m in measures]
        self.info = info
        self.stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.file_stamp = time.strftime("%Y%m%d_%H%M%S")
        self.thumb_label = None

def render_capture(cap, with_measures=True, s=CAP_SCALE):
    """Compose a standalone still: B-mode + axes + footer (+ calipers)."""
    iw, ih = cap.img.width(), cap.img.height()
    ml, mt, mr, mb = int(ML*s), int(MT*s), int(MR*s), int(MB*s)
    foot = int(20 * s)
    out = QImage(iw + ml + mr, ih + mt + mb + foot, QImage.Format_RGB32)
    out.fill(QColor(PLOT_BG))
    p = QPainter(out)
    r = QRectF(ml, mt, iw, ih)
    p.drawImage(QPointF(ml, mt), cap.img)
    paint_axes(p, r, cap.vb, s)
    if with_measures:
        paint_measures(p, r, cap.vb, cap.measures, s)
    p.setFont(QFont("Consolas", max(6, int(8 * s))))
    p.setPen(QPen(QColor(DIM)))
    fm = QFontMetrics(p.font())
    p.drawText(QPointF(ml, mt + ih + mb + (foot + fm.ascent()) / 2),
               f"#{cap.n}  {cap.stamp}   {cap.info}")     # in the footer band,
                                                          # clear of the axis text
    p.end()
    return out

class CaptureView(MeasureCanvas):
    """A still, scaled to fit, with the same caliper interaction as the live
    view.  Wheel/drag here zoom the bitmap (the beamformer is not re-run), which
    is what you want for placing calipers precisely on a frozen image."""
    def __init__(self, cap, parent=None):
        super().__init__(parent)
        self.cap = cap
        self.base = render_capture(cap, with_measures=False)
        self.measures = cap.measures            # edit in place
        self.vb = cap.vb
        self._rect = QRectF(0, 0, 1, 1)
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._grab = None
        self.setMinimumSize(520, 420)
        self.setFocusPolicy(Qt.StrongFocus)

    def _dst(self):
        bw, bh = self.base.width(), self.base.height()
        k = min(self.width() / bw, self.height() / bh) * self.zoom
        w, h = bw * k, bh * k
        return QRectF((self.width()-w)/2 + self.pan.x(),
                      (self.height()-h)/2 + self.pan.y(), w, h), k

    def image_rect(self):
        return self._rect

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if steps:
            before = ev.position() - self._dst()[0].topLeft()
            self.zoom = min(max(self.zoom * (1.25 ** steps), 1.0), 16.0)
            after = ev.position() - self._dst()[0].topLeft()
            self.pan += after - before      # keep the point under the cursor
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or \
           (ev.button() == Qt.LeftButton and ev.modifiers() & Qt.ControlModifier):
            self._grab = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._grab is not None:
            self.pan += ev.position() - self._grab
            self._grab = ev.position()
            self.update()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._grab is not None:
            self._grab = None
            self.setCursor(Qt.CrossCursor)
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if not self._pick(ev.position()):
            self.zoom, self.pan = 1.0, QPointF(0, 0)
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        dst, k = self._dst()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(dst, self.base)
        # where the B-mode sub-rect landed inside the scaled composite
        self._rect = QRectF(dst.left() + ML*CAP_SCALE*k, dst.top() + MT*CAP_SCALE*k,
                            self.cap.img.width()*k, self.cap.img.height()*k)
        paint_measures(p, self._rect, self.vb, self.measures,
                       max(0.8, k * CAP_SCALE), self.hot)
        p.end()

class CaptureDialog(QDialog):
    def __init__(self, cap, on_change, parent=None):
        super().__init__(parent)
        self.cap, self.on_change = cap, on_change
        self.setWindowTitle(f"capture #{cap.n} - {cap.stamp}")
        self.setStyleSheet(APP_QSS)
        v = QVBoxLayout(self); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        self.view = CaptureView(cap, self)
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        hint = QLabel("drag to measure · drag ends or the middle to adjust · "
                      "right-click a line to delete · wheel zooms, ctrl-drag pans")
        hint.setStyleSheet(f"color:{DIM};")
        row.addWidget(hint); row.addStretch(1)
        b_clr = QPushButton("clear measurements"); b_clr.clicked.connect(self._clear)
        b_sav = QPushButton("save PNG…");          b_sav.clicked.connect(self._save)
        b_cls = QPushButton("close");              b_cls.clicked.connect(self.close)
        for b in (b_clr, b_sav, b_cls): row.addWidget(b)
        v.addLayout(row)
        self.view.changed.connect(self._touched)
        self.resize(900, 780)

    def _touched(self):
        self.cap.measures = self.view.measures
        self.on_change(self.cap)

    def _clear(self):
        self.view.clear_measures()

    def _save(self):
        save_capture(self.cap, self)

def save_capture(cap, parent):
    path, _ = QFileDialog.getSaveFileName(
        parent, "save B-mode capture",
        os.path.join(os.path.expanduser("~"), "Pictures",
                     f"bmode_{cap.file_stamp}_{cap.n:03d}.png"),
        "PNG image (*.png)")
    if not path:
        return
    if render_capture(cap).save(path, "PNG"):
        print(f"saved {path}")
    else:
        print(f"FAILED to save {path}")

class ThumbLabel(QLabel):
    clicked = Signal()
    removed = Signal()
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        elif ev.button() == Qt.RightButton:
            self.removed.emit()

#===============================================================================
# controls
#===============================================================================
APP_QSS = f"""
QWidget {{ background:{BG}; color:{FG}; font-family:Consolas; font-size:11px; }}
QLabel  {{ background:transparent; }}
QPushButton {{ background:#1a2129; border:1px solid #2c3a45; padding:4px 9px;
              border-radius:3px; }}
QPushButton:hover  {{ background:#22303a; }}
QPushButton:pressed{{ background:#2c3f4c; }}
QPushButton:checked{{ background:#8a3a1e; border-color:#c25a2c; color:#ffe; }}
QPushButton:disabled {{ color:#3d4a55; border-color:#1e262e; }}
QPushButton:checked:disabled {{ background:#33221a; border-color:#4a3226; }}
QCheckBox {{ spacing:4px; }}
QSlider::groove:horizontal {{ height:3px; background:#2a3540; border-radius:2px; }}
QSlider::handle:horizontal {{ width:10px; margin:-5px 0; border-radius:5px;
                              background:#6fa8c9; }}
QSlider::sub-page:horizontal {{ background:#3d6c88; border-radius:2px; }}
QScrollArea {{ border:1px solid #22303a; }}
QFrame#panel {{ border:1px solid #22303a; border-radius:3px; }}
"""

def mkslider(row, label, lo, hi, val, on_change=None, on_release=None,
             width=104, unit=""):
    box = QWidget()
    l = QHBoxLayout(box); l.setContentsMargins(5, 0, 5, 0); l.setSpacing(4)
    lab = QLabel(label); lab.setStyleSheet(f"color:{DIM};")
    s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(val)
    s.setFixedWidth(width)
    vl = QLabel(f"{val}{unit}"); vl.setFixedWidth(42)
    vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    def _ch(v):
        vl.setText(f"{v}{unit}")
        if on_change: on_change(v)
    s.valueChanged.connect(_ch)
    if on_release:
        s.sliderReleased.connect(lambda: on_release(s.value()))
    l.addWidget(lab); l.addWidget(s); l.addWidget(vl)
    row.addWidget(box)
    return s

#===============================================================================
# cine transport: play/step/repeat buttons, scrub timeline, speed knob
#===============================================================================
class GlyphButton(QPushButton):
    """Transport button that paints its own icon, so the look never depends on
    the monospace font happening to carry play/pause/loop glyphs.  The frame,
    hover and checked states still come from the app stylesheet."""
    def __init__(self, kind, tip="", checkable=False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self.setFixedSize(32, 26)

    def set_kind(self, kind):
        self._kind = kind
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor("#3d4a55") if not self.isEnabled() else \
              QColor("#ffeedd" if self.isChecked() else FG)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        k = self._kind
        if k == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - 4, cy - 6), QPointF(cx - 4, cy + 6),
                                     QPointF(cx + 6, cy)]))
        elif k == "pause":
            p.drawRect(QRectF(cx - 5.2, cy - 6, 3.4, 12))
            p.drawRect(QRectF(cx + 1.8, cy - 6, 3.4, 12))
        elif k in ("step-", "step+"):
            s = -1.0 if k == "step-" else 1.0
            p.drawPolygon(QPolygonF([QPointF(cx - 3*s, cy - 6), QPointF(cx - 3*s, cy + 6),
                                     QPointF(cx + 4*s, cy)]))
            p.drawRect(QRectF(cx + (4 if s > 0 else -6), cy - 6, 2.0, 12))
        elif k == "repeat":
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 1.7))
            p.drawArc(QRectF(cx - 7, cy - 6, 14, 12), 35*16, 290*16)
            a  = np.radians(35.0)
            tp = QPointF(cx + 7*np.cos(a), cy - 6*np.sin(a))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(col))
            p.drawPolygon(QPolygonF([tp + QPointF(-3.6, -2.4), tp + QPointF(3.2, -1.0),
                                     tp + QPointF(-0.6, 3.6)]))
        p.end()

class Knob(QWidget):
    """Log-scaled rotary control: drag up/down or wheel to change, double-click
    to snap back to the detent.  Log scaling is what makes 0.1x and 4x equally
    reachable from 1x, which a linear slider cannot do."""
    changed = Signal(float)

    def __init__(self, lo, hi, val, detent=1.0, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.detent = float(lo), float(hi), float(detent)
        self.val = float(val)
        self._y  = None
        self.setFixedSize(42, 42)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("drag or wheel to change replay speed\n"
                        "double-click (or the 1x button) resets to real time")

    def _f(self, v=None):
        v = self.val if v is None else v
        return float(np.log(v / self.lo) / np.log(self.hi / self.lo))

    def set_val(self, v, emit=True):
        v = float(min(max(v, self.lo), self.hi))
        if abs(v - self.val) < 1e-9:
            return
        self.val = v
        self.update()
        if emit:
            self.changed.emit(v)

    def _set_f(self, f):
        self.set_val(self.lo * (self.hi / self.lo) ** min(max(f, 0.0), 1.0))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._y = ev.position().y()

    def mouseMoveEvent(self, ev):
        if self._y is None:
            return
        dy, self._y = self._y - ev.position().y(), ev.position().y()
        self._set_f(self._f() + dy / 120.0)

    def mouseReleaseEvent(self, ev):
        self._y = None

    def mouseDoubleClickEvent(self, ev):
        self.set_val(self.detent)

    def wheelEvent(self, ev):
        s = ev.angleDelta().y() / 120.0
        if s:
            self._set_f(self._f() + s * 0.04)

    def _spoke(self, p, r, f, r0, r1, col, w):
        a  = np.radians(225.0 - 270.0 * f)      # 8 o'clock -> 4 o'clock, cw
        c0 = r.center()
        p.setPen(QPen(QColor(col), w))
        p.drawLine(QPointF(c0.x() + r0*np.cos(a), c0.y() - r0*np.sin(a)),
                   QPointF(c0.x() + r1*np.cos(a), c0.y() - r1*np.sin(a)))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r  = QRectF(6, 6, self.width() - 12, self.height() - 12)
        rr = r.width() / 2.0
        p.setPen(QPen(QColor("#2a3540"), 3.0))
        p.drawArc(r, 225*16, -270*16)
        f = self._f()
        p.setPen(QPen(QColor("#6fa8c9"), 3.0))
        p.drawArc(r, 225*16, int(-270*16*f))
        self._spoke(p, r, self._f(self.detent), rr - 4, rr + 3, "#4c6272", 1.2)
        self._spoke(p, r, f, rr - 9, rr - 1, "#cfe6f5", 2.0)
        p.end()

class Timeline(QWidget):
    """Scrub bar over the cine buffer.  Labelled relative to the newest frame,
    so the strip reads directly as how far back in time you are."""
    scrubbed = Signal(float)            # seconds from the oldest held frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self.span = 0.0                 # seconds held
        self.pos  = 0.0                 # play head
        self.live = True                # recording: no head, whole bar filled
        self._drag = False
        self.setFixedHeight(40)
        self.setCursor(Qt.SizeHorCursor)

    def track(self):
        return QRectF(9, 7, max(1.0, self.width() - 18), 13)

    def _t_at(self, x):
        r = self.track()
        return min(max((x - r.left()) / r.width(), 0.0), 1.0) * self.span

    def _x_at(self, t):
        r = self.track()
        return r.left() + r.width() * (t / self.span if self.span > 0 else 0.0)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self.live and self.span > 0:
            self._drag = True
            self.scrubbed.emit(self._t_at(ev.position().x()))

    def mouseMoveEvent(self, ev):
        if self._drag:
            self.scrubbed.emit(self._t_at(ev.position().x()))

    def mouseReleaseEvent(self, ev):
        self._drag = False

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.track()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#161e26")))
        p.drawRoundedRect(r, 3, 3)
        p.setFont(QFont("Consolas", 7))
        fm = QFontMetrics(p.font())
        if self.span <= 0.0:
            p.setPen(QPen(QColor(DIM)))
            p.drawText(QPointF(r.left() + 6, r.center().y() + fm.ascent()/2 - 1),
                       "cine buffer empty")
            p.end(); return

        if self.live:                   # recording: the whole span is "now"
            p.setBrush(QBrush(QColor("#23404f")))
            p.drawRoundedRect(r, 3, 3)
        else:
            fr = QRectF(r.left(), r.top(), max(1.0, r.width()*self.pos/self.span),
                        r.height())
            p.setBrush(QBrush(QColor("#2d5670")))
            p.drawRoundedRect(fr, 3, 3)

        step = 1.0 if self.span <= 12 else (2.0 if self.span <= 30 else 5.0)
        p.setPen(QPen(QColor(DIM)))
        k = 0
        while k * step <= self.span + 1e-9:
            tv = self.span - k * step               # 0 s sits at the right edge
            x  = self._x_at(tv)
            p.drawLine(QPointF(x, r.bottom() + 1), QPointF(x, r.bottom() + 4))
            t = f"{-k*step:g}"
            tx = min(max(x - fm.horizontalAdvance(t)/2, 0.0),
                     self.width() - fm.horizontalAdvance(t))
            p.drawText(QPointF(tx, r.bottom() + 5 + fm.ascent()), t)
            k += 1

        if not self.live:
            x = self._x_at(self.pos)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#cfe6f5")))
            p.drawRoundedRect(QRectF(x - 2.5, r.top() - 3, 5, r.height() + 6), 2, 2)
        p.end()

#===============================================================================
# main window
#===============================================================================
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TFM B-mode - {N_ELEM} element convex, monostatic "
                            f"(SAFT), GPU beamformer"
                            + ("" if HW else "  [SIMULATION]"))
        self.captures = []
        self.dialogs = []
        self.last = None
        self.tgc_lo, self.tgc_hi = TGC_MIN_DEF, TGC_MAX_DEF
        self.gap = GAP_US_DEF

        # cine review state (only meaningful while frozen)
        self.review  = []               # [(t_abs, (N, samps) int16)], oldest first
        self.rev_t   = np.zeros(0)      # their timestamps, seconds from the oldest
        self.cur_idx = -1
        self.play_t  = 0.0              # play head, seconds into the buffer
        self.playing = False
        self.speed   = SPEED_DEF
        self._play_wall = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 5); root.setSpacing(4)

        # -- control rows -----------------------------------------------------
        r1 = QHBoxLayout(); r1.setSpacing(2); root.addLayout(r1)
        r2 = QHBoxLayout(); r2.setSpacing(2); root.addLayout(r2)

        self.cb_signed = QCheckBox("signed"); self.cb_signed.setChecked(mode["signed"])
        self.cb_signed.toggled.connect(lambda v: mode.__setitem__("signed", v))
        r1.addWidget(self.cb_signed)

        self.depth_s = mkslider(r1, "depth", 2, 40, DEPTH_CM_DEF,
                                on_release=self.apply_depth, unit="cm")
        self.dly_s = mkslider(r1, "pulse→rx", 0, 500, DLY_US_DEF,
                              on_change=self.set_dly, unit="us")
        mkslider(r1, "damp", 0, 5000, GAP_US_DEF, on_release=self.set_gap,
                 width=90, unit="us")
        mkslider(r1, "c", 1400, 1650, int(C_DEF), on_change=self.set_c,
                 width=96, unit="")
        mkslider(r1, "aperture", 5, 90, ACCEPT_DEF, on_change=self.set_accept,
                 width=84, unit="°")
        r1.addStretch(1)

        mkslider(r2, "TGC min", 0, 4095, TGC_MIN_DEF, on_change=self.set_tgc_lo,
                 width=118)
        mkslider(r2, "TGC max", 0, 4095, TGC_MAX_DEF, on_change=self.set_tgc_hi,
                 width=118)
        mkslider(r2, "dyn range", 20, 80, DYN_DEF, on_change=self.set_dyn,
                 width=96, unit="dB")
        mkslider(r2, "gain", -40, 40, GAIN_DEF, on_change=self.set_gain,
                 width=96, unit="dB")
        self.cb_auto = QCheckBox("auto gain"); self.cb_auto.setChecked(True)
        self.cb_auto.setToolTip("normalise to the per-frame peak; off = absolute "
                                "scale, use the gain slider")
        self.cb_auto.toggled.connect(self.set_auto)
        r2.addWidget(self.cb_auto)
        r2.addStretch(1)
        r2.addSpacing(14)
        self.wininfo = QLabel(""); self.wininfo.setStyleSheet(f"color:{DIM};")
        r2.addWidget(self.wininfo)

        # -- scene + cine transport + side panel ------------------------------
        mid = QHBoxLayout(); mid.setSpacing(6); root.addLayout(mid, 1)
        self.scene = Scene(self)
        col = QVBoxLayout(); col.setSpacing(4)
        col.addWidget(self.scene, 1)
        col.addWidget(self._cine_bar())     # built before the panel: FREEZE's
        mid.addLayout(col, 1)               # handler touches it
        mid.addWidget(self._side_panel())
        self.scene.ov.zoomed.connect(self._zoom_text)

        # -- capture drawer ---------------------------------------------------
        self.drawer_box = QWidget()
        dl = QHBoxLayout(self.drawer_box)
        dl.setContentsMargins(4, 4, 4, 4); dl.setSpacing(5)
        dl.addStretch(1)
        self.drawer_layout = dl
        self.drawer = QScrollArea()
        self.drawer.setWidgetResizable(True)
        self.drawer.setFixedHeight(THUMB_H + 26)
        self.drawer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.drawer.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.drawer.setWidget(self.drawer_box)
        root.addWidget(self.drawer)

        self.status = QLabel("starting…")
        self.status.setStyleSheet(f"color:{OK_C};")
        root.addWidget(self.status)

        # -- timers -----------------------------------------------------------
        self.t_draw = QTimer(self); self.t_draw.timeout.connect(self._tick)
        self.t_draw.start(16)
        self.t_stat = QTimer(self); self.t_stat.timeout.connect(self._status)
        self.t_stat.start(250)
        # replay clock: 10 ms is finer than any frame interval we can record,
        # so the play head lands on the right frame even at 4x
        self.t_play = QTimer(self); self.t_play.timeout.connect(self._play_tick)

        for key, fn in ((Qt.Key_Space,  self._space),
                        (Qt.Key_Escape, lambda: self.b_freeze.setChecked(False)),
                        (Qt.Key_Comma,  lambda: self.step(-1)),
                        (Qt.Key_Period, lambda: self.step(+1))):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

        self._cine_enable(False)
        self.resize(1320, 900)

    # -- cine transport bar ---------------------------------------------------
    def _cine_bar(self):
        bar = QFrame(); bar.setObjectName("panel")
        h = QHBoxLayout(bar); h.setContentsMargins(7, 4, 7, 4); h.setSpacing(5)

        self.b_play   = GlyphButton("play",  "play the cine loop  (space)")
        self.b_stepb  = GlyphButton("step-", "previous frame  (,)")
        self.b_stepf  = GlyphButton("step+", "next frame  (.)")
        self.b_rep    = GlyphButton("repeat", "loop back to the start at the end",
                                    checkable=True)
        self.b_rep.setChecked(True)
        self.b_play.clicked.connect(self.toggle_play)
        self.b_stepb.clicked.connect(lambda: self.step(-1))
        self.b_stepf.clicked.connect(lambda: self.step(+1))
        for b in (self.b_play, self.b_stepb, self.b_stepf, self.b_rep):
            h.addWidget(b)

        self.tl = Timeline()
        self.tl.scrubbed.connect(self.scrub)
        h.addWidget(self.tl, 1)

        self.cine_lbl = QLabel("")
        self.cine_lbl.setStyleSheet(f"color:{DIM};")
        self.cine_lbl.setFixedWidth(178)
        self.cine_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.cine_lbl)

        kv = QVBoxLayout(); kv.setSpacing(0); kv.setContentsMargins(2, 0, 0, 0)
        self.knob = Knob(SPEED_MIN, SPEED_MAX, SPEED_DEF)
        self.knob.changed.connect(self.set_speed)
        kv.addWidget(self.knob, 0, Qt.AlignHCenter)
        self.spd_lbl = QLabel("1.00x")
        self.spd_lbl.setStyleSheet(f"color:{DIM};")
        self.spd_lbl.setAlignment(Qt.AlignHCenter)
        kv.addWidget(self.spd_lbl)
        h.addLayout(kv)

        b_1x = QPushButton("1x")
        b_1x.setToolTip("back to real time")
        b_1x.setFixedWidth(30)
        b_1x.clicked.connect(lambda: self.knob.set_val(SPEED_DEF))
        h.addWidget(b_1x)
        return bar

    # -- side panel -----------------------------------------------------------
    def _side_panel(self):
        panel = QFrame(); panel.setObjectName("panel"); panel.setFixedWidth(248)
        v = QVBoxLayout(panel); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        self.b_freeze = QPushButton("FREEZE")
        self.b_freeze.setCheckable(True)
        self.b_freeze.setFixedHeight(30)
        self.b_freeze.setToolTip(f"pause and review the last {CINE_SECONDS:.0f} s "
                                 f"on the timeline below the image  (space)")
        self.b_freeze.toggled.connect(self.set_frozen)
        v.addWidget(self.b_freeze)

        self.b_cap = QPushButton("CAPTURE")
        self.b_cap.setFixedHeight(30)
        self.b_cap.clicked.connect(self.do_capture)
        v.addWidget(self.b_cap)

        row0 = QHBoxLayout(); row0.setSpacing(4)
        self.zoom_lbl = QLabel("zoom 1.0x")
        self.zoom_lbl.setStyleSheet(f"color:{DIM};")
        b_rst = QPushButton("reset view"); b_rst.clicked.connect(self.reset_view)
        row0.addWidget(self.zoom_lbl); row0.addStretch(1); row0.addWidget(b_rst)
        v.addLayout(row0)

        lb = QLabel("last capture"); lb.setStyleSheet(f"color:{DIM};")
        v.addWidget(lb)
        self.preview = QLabel()
        self.preview.setFixedHeight(186)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"border:1px solid #22303a; background:{PLOT_BG};"
                                   f"color:{DIM};")
        self.preview.setText("no captures yet")
        v.addWidget(self.preview)

        row = QHBoxLayout(); row.setSpacing(4)
        self.b_open = QPushButton("open"); self.b_open.clicked.connect(self.open_last)
        self.b_save = QPushButton("save PNG…"); self.b_save.clicked.connect(self.save_last)
        self.b_open.setEnabled(False); self.b_save.setEnabled(False)
        row.addWidget(self.b_open); row.addWidget(self.b_save)
        v.addLayout(row)

        v.addSpacing(4)
        b_clr = QPushButton("clear measurements")
        b_clr.clicked.connect(self.scene.ov.clear_measures)
        v.addWidget(b_clr)
        self.meas_lbl = QLabel("no measurements")
        self.meas_lbl.setWordWrap(True)
        self.meas_lbl.setStyleSheet(f"color:{MEAS_C};")
        v.addWidget(self.meas_lbl)
        self.scene.ov.changed.connect(self._meas_text)

        v.addStretch(1)
        tip = QLabel("wheel zooms about the cursor\n"
                     "middle- or ctrl-drag pans\n"
                     "double-click resets the view\n"
                     "drag on the image to measure\n"
                     "drag an end or the middle to adjust\n"
                     "right-click a line to delete\n"
                     "click a thumbnail to reopen it\n"
                     "\n"
                     "space freezes, then plays the loop\n"
                     "drag the timeline to go back in time\n"
                     ", and . step one frame\n"
                     "esc goes back to live")
        tip.setStyleSheet(f"color:{DIM};")
        v.addWidget(tip)
        return panel

    def _meas_text(self):
        ms = self.scene.ov.measures
        if not ms:
            self.meas_lbl.setText("no measurements")
        else:
            self.meas_lbl.setText("   ".join(f"{i+1}: {meas_mm(m):.1f} mm"
                                             for i, m in enumerate(ms)))

    def _zoom_text(self):
        self.zoom_lbl.setText(f"zoom {view['zoom']:.1f}x")

    def reset_view(self):
        reset_view()
        self._zoom_text()
        self.scene.gl.update()

    # -- control callbacks ----------------------------------------------------
    def set_dly(self, v):
        state["dly_us"] = float(v)
        send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(v)), "seq_dly")

    def set_gap(self, v):
        self.gap = v
        send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(v)), "seq_gap")

    # these are pure shader uniforms - repaint explicitly so they stay live
    # while frozen (only the compress pass re-runs for dyn range / gain)
    def set_c(self, v):       state["c"] = float(v);      self.scene.gl.update()
    def set_accept(self, v):  state["accept"] = float(v); self.scene.gl.update()
    def set_dyn(self, v):     state["dyn"] = float(v);    self.scene.gl.update()
    def set_gain(self, v):    state["gain"] = float(v);   self.scene.gl.update()

    def _send_tgc(self):
        lo, hi = self.tgc_lo, max(self.tgc_lo, self.tgc_hi)
        inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
        send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
        send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

    def set_tgc_lo(self, v): self.tgc_lo = v; self._send_tgc()
    def set_tgc_hi(self, v): self.tgc_hi = v; self._send_tgc()

    def set_auto(self, v):
        state["auto"] = v
        self.scene.gl.update()

    def set_frozen(self, v):
        """FREEZE is also the entry point to the cine loop: it stops the
        recorder and takes a stable snapshot of everything still in it, so the
        frames cannot shift under the timeline while it is being scrubbed."""
        state["frozen"] = v
        self.b_freeze.setText("FROZEN - click to resume" if v else "FREEZE")
        if v:
            self.review, self.rev_t = cine.freeze()
            self.cur_idx = -1
            self._cine_enable(True)
            if len(self.review):
                self.play_t = float(self.rev_t[-1])     # sit on the newest frame
                self._seek(self.play_t, force=True)     # ...and show exactly it
            else:
                self._cine_text()
        else:
            self._stop_play()
            self.review, self.rev_t = [], np.zeros(0)
            self.cur_idx = -1
            with replay_lk:         # drop any in-flight request before the
                replay["rf"] = None # recorder can recycle the slot it points at
            cine.resume()
            self._cine_enable(False)
            hil_ev.set()                  # wake the worker back up

    # -- cine transport -------------------------------------------------------
    def _cine_enable(self, on):
        for w in (self.b_play, self.b_stepb, self.b_stepf, self.b_rep):
            w.setEnabled(on)
        self.tl.live = not on
        self.tl.update()

    def _span(self):
        return float(self.rev_t[-1]) if len(self.rev_t) else 0.0

    def _seek(self, t, force=False):
        """Show the frame that was live at `t` seconds into the buffer."""
        if not self.review:
            return
        t = min(max(t, 0.0), self._span())
        i = int(np.searchsorted(self.rev_t, t, side="right")) - 1
        i = min(max(i, 0), len(self.review) - 1)
        if i != self.cur_idx or force:
            self.cur_idx = i
            request_replay(self.review[i][1])
        self.play_t = t
        self.tl.span, self.tl.pos = self._span(), t
        self.tl.update()
        self._cine_text()

    def _cine_text(self):
        if not self.review:
            self.cine_lbl.setText("no frames buffered")
            return
        self.cine_lbl.setText(f"{self.play_t - self._span():+6.2f} s   "
                              f"{self.cur_idx + 1}/{len(self.review)}")

    def scrub(self, t):
        self._play_wall = time.perf_counter()    # dragging must not "catch up"
        self._seek(t)

    def step(self, d):
        if not self.review or not state["frozen"]:
            return
        self._stop_play()
        i = min(max(self.cur_idx + d, 0), len(self.review) - 1)
        self._seek(float(self.rev_t[i]), force=(i == self.cur_idx))

    def toggle_play(self):
        if self.playing:
            self._stop_play()
        elif self.review:
            if self.play_t >= self._span() - 1e-6:      # parked at the end
                self._seek(0.0)
            self.playing = True
            self.b_play.set_kind("pause")
            self._play_wall = time.perf_counter()
            self.t_play.start(10)

    def _stop_play(self):
        self.playing = False
        self.t_play.stop()
        self.b_play.set_kind("play")

    def _play_tick(self):
        """Walk the play head in recorded time, so 1x replays the loop at the
        rate it was acquired at, gaps and jitter included."""
        now = time.perf_counter()
        dt, self._play_wall = now - self._play_wall, now
        t = self.play_t + dt * self.speed
        if t >= self._span():
            if self.b_rep.isChecked():
                t = 0.0 if self._span() <= 0 else t % self._span()
            else:
                self._seek(self._span())
                self._stop_play()
                return
        self._seek(t)

    def set_speed(self, v):
        self.speed = float(v)
        self.spd_lbl.setText(f"{v:.2f}x")

    def _space(self):
        if state["frozen"]:
            self.toggle_play()
        else:
            self.b_freeze.setChecked(True)

    def apply_depth(self, v):
        """Depth changes the frame size: stop, drain, swap buffers, reconfigure."""
        global raw_buf, carry, _prev_elem
        words = depth_to_words(v)
        if words == cfg["win_words"]:
            return
        state["depth_cm"] = v
        # the recorded windows are the old length: nothing in them can be shown
        # against the new geometry, so the loop starts over (and cannot stay
        # frozen on frames that are about to be discarded)
        self.b_freeze.setChecked(False)
        cine.reset()
        send_cmd(cmd(OP_STOP), "stop")
        time.sleep(0.2)                       # residual old-size frames drain
        with buf_lk:
            set_cfg(words)
            raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)
            carry = np.empty(0, dtype=np.uint32)
            stats["last_fcnt"] = None
            _prev_elem = -1
        send_seq_config(self.tgc_lo, max(self.tgc_lo, self.tgc_hi),
                        int(state["dly_us"]), self.gap)
        send_cmd(cmd(OP_START), "start")
        view["cz"] = None                     # depth changed: recentre vertically

    # -- capture --------------------------------------------------------------
    def info_line(self):
        return (f"{N_ELEM} el  depth {state['depth_cm']} cm  c {state['c']:.0f} m/s  "
                f"dly {state['dly_us']:.0f} us  aper {state['accept']:.0f} deg  "
                f"dyn {state['dyn']:.0f} dB  gain {state['gain']:+.0f} dB  "
                f"zoom {view['zoom']:.1f}x  TGC {self.tgc_lo}-"
                f"{max(self.tgc_lo, self.tgc_hi)}"
                + (f"  cine {self.play_t - self._span():+.2f} s"
                   if state["frozen"] and self.review else "")
                + ("" if HW else "  [SIM]"))

    def do_capture(self):
        img, vb = self.scene.gl.grab_bmode()
        if img is None:
            return
        cap = Capture(img, vb, self.scene.ov.measures, self.info_line())
        self.captures.append(cap)
        self._add_thumb(cap)
        self._set_preview(cap)
        self.b_open.setEnabled(True); self.b_save.setEnabled(True)

    def _set_preview(self, cap):
        pm = QPixmap.fromImage(render_capture(cap))
        self.preview.setPixmap(pm.scaled(self.preview.width() - 4,
                                         self.preview.height() - 4,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview.setToolTip(f"#{cap.n}  {cap.stamp}")
        self.last = cap

    def _thumb_pixmap(self, cap):
        return QPixmap.fromImage(render_capture(cap)).scaledToHeight(
            THUMB_H, Qt.SmoothTransformation)

    def _add_thumb(self, cap):
        lb = ThumbLabel()
        lb.setPixmap(self._thumb_pixmap(cap))
        lb.setToolTip(f"#{cap.n}  {cap.stamp}\nclick to open · right-click to remove")
        lb.setStyleSheet("border:1px solid #2c3a45;")
        lb.setCursor(Qt.PointingHandCursor)
        lb.clicked.connect(lambda c=cap: self.open_capture(c))
        lb.removed.connect(lambda c=cap: self.remove_capture(c))
        cap.thumb_label = lb
        self.drawer_layout.insertWidget(self.drawer_layout.count() - 1, lb)
        QTimer.singleShot(0, lambda: self.drawer.horizontalScrollBar().setValue(
            self.drawer.horizontalScrollBar().maximum()))

    def capture_changed(self, cap):
        """Measurements edited in a viewer: refresh its thumbnail and preview."""
        if cap.thumb_label is not None:
            cap.thumb_label.setPixmap(self._thumb_pixmap(cap))
        if self.last is cap:
            self._set_preview(cap)

    def open_capture(self, cap):
        dlg = CaptureDialog(cap, self.capture_changed, self)
        self.dialogs.append(dlg)
        dlg.show()

    def remove_capture(self, cap):
        if cap.thumb_label is not None:
            self.drawer_layout.removeWidget(cap.thumb_label)
            cap.thumb_label.deleteLater()
            cap.thumb_label = None
        if cap in self.captures:
            self.captures.remove(cap)
        if self.last is cap:
            if self.captures:
                self._set_preview(self.captures[-1])
            else:
                self.last = None
                self.preview.setPixmap(QPixmap())
                self.preview.setText("no captures yet")
                self.b_open.setEnabled(False); self.b_save.setEnabled(False)

    def open_last(self):
        if self.last:
            self.open_capture(self.last)

    def save_last(self):
        if self.last:
            save_capture(self.last, self)

    # -- frame / status -------------------------------------------------------
    def _tick(self):
        self.scene.sync_view()
        gl = self.scene.gl
        if gl.tex_gen != hil["gen"] or gl.rf_tex is None:
            gl.update()
        self.scene.ov.update()

    def _status(self):
        gl = self.scene.gl
        if not state["frozen"]:             # live: the bar shows the buffer fill
            n, secs, mb = cine.status()
            self.tl.span = secs
            self.tl.update()
            self.cine_lbl.setText(f"rec {n} f · {secs:4.1f} s · {mb:.0f} MB")
        self.wininfo.setText(
            f"win {cfg['samps']} samp · {cfg['win_us']:.0f} us · "
            f"grid {gl.fb_w}x{gl.fb_h} · {N_ELEM} el, {APERTURE_MM:g} mm aperture "
            f"· R {PROBE_R_MM:g} mm pitch {PITCH_MM:g} mm")
        bad = stats["drops"] or stats["resyncs"]
        self.status.setText(
            f" {stats['mbps']:6.1f} MB/s   {stats['fps']/N_ELEM:6.1f} sweeps/s"
            f"   frames {stats['frames']}   drops {stats['drops']}"
            f"   resyncs {stats['resyncs']}"
            f"   |  gpu {perf['gpu_ms']:.2f} ms   ui {perf['cpu_ms']:.2f} ms"
            f"   hilbert {perf['hil_ms']:.1f} ms ({FFT_LIB}, off-thread)"
            + ("" if stats["alive"] else "   *** STREAM STOPPED ***"))
        self.status.setStyleSheet(f"color:{WARN_C if bad else OK_C};")

    def closeEvent(self, ev):
        stats["alive"] = False
        hil_ev.set()                      # let the worker notice and exit
        if HW:
            try:
                send_cmd(cmd(OP_STOP), "stop")
            except SystemExit:
                pass
            time.sleep(0.1)
            for i in range(NBUF):
                d3.FT_ReleaseOverlapped(h, C.byref(ovs[i]))
            d3.FT_Close(h)
        ev.accept()

#===============================================================================
if __name__ == "__main__":
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapInterval(0)          # no vsync: lowest latency, never blocks the UI
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    win = Main()
    win.show()
    print("streaming - close the window to stop.")
    sys.exit(app.exec())
