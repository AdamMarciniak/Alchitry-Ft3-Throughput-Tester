# ft601_host.py
#   python ft601_host.py        -> lock, START counter stream, raw ceiling
#   python ft601_host.py v      -> same, plus verify counter is gapless
#   python ft601_host.py v lfsr -> stream the LFSR pattern (ceiling only)
#   python ft601_host.py lock   -> DIAGNOSTIC: send ONE lock word, then hold
#
# Raw-DLL host for the FT601 throughput tester.  Two pipes on one handle:
#   * control  PC -> FPGA : WRITE pipe 0x02, small synchronous FT_WritePipe
#   * data     FPGA -> PC : READ  pipe 0x82, overlapped FT_ReadPipeEx ring
#
# Since ctrl_decode.v now gates streaming on a START command, the FPGA emits
# nothing until we configure it.  Bring-up order (matches the handoff):
#   1. send 0xA5A55A5A            - RX-latency lock word, MUST be first
#   2. SET_PAT / RST_CNT / LIMIT  - configure the pattern source
#   3. arm the read ring, then START
#   4. stream (and optionally verify), STOP on exit
#
# Every control command is a single 4-byte write.  Never batch them - the
# FPGA would decode the padding bytes as further commands.
import ctypes as C, sys, time
import numpy as np
import os
import struct

print(f"Python is {'64-bit' if struct.calcsize('P') == 8 else '32-bit'}")

XFER, NBUF        = 1024*1024, 8
PIPE_IN, PIPE_OUT = 0x82, 0x02          # data read / control write
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10

# --- control protocol (matches ctrl_decode.v) --------------------------------
LOCK_WORD = 0xA5A55A5A
OP_NOP, OP_START, OP_STOP, OP_RST_CNT, OP_SET_PAT, OP_SET_CONST, OP_SET_LIMIT = \
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06
PAT_COUNTER, PAT_LFSR, PAT_CONST = 0, 1, 2

# FT_STATUS enum -> name (D3XX), so errors are readable
FT_STATUS_NAMES = {
    0: "FT_OK", 1: "FT_INVALID_HANDLE", 2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED", 4: "FT_IO_ERROR", 5: "FT_INSUFFICIENT_RESOURCES",
    6: "FT_INVALID_PARAMETER", 16: "FT_INVALID_ARGS", 17: "FT_NOT_SUPPORTED",
    18: "FT_NO_MORE_ITEMS", 19: "FT_TIMEOUT", 20: "FT_OPERATION_ABORTED",
    21: "FT_RESERVED_PIPE", 22: "FT_INVALID_CONTROL_REQUEST",
}
def ft_status(st):
    return FT_STATUS_NAMES.get(st, f"0x{st:X}")

# Get the full path to the DLL in the same folder as this script
dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FTD3XX.dll")
print(f"Trying to load: {dll_path}")
print(f"File exists: {os.path.exists(dll_path)}")

try:
    d3 = C.WinDLL(dll_path)
    print("DLL loaded successfully!")
except OSError as e:
    print(f"Failed to load DLL: {e}")
    print("\nThis usually means the DLL architecture doesn't match your Python.")
    print(f"If Python is 64-bit, you need the 64-bit version of FTD3XX.dll")
    print(f"If Python is 32-bit, you need the 32-bit version of FTD3XX.dll")
    sys.exit(1)

d3.FT_Create.restype    = C.c_ulong     # FT_STATUS is ULONG
d3.FT_WritePipe.restype = C.c_ulong

class OVERLAPPED(C.Structure):
    _fields_ = [("Internal", C.c_void_p), ("InternalHigh", C.c_void_p),
                ("Pointer",  C.c_void_p), ("hEvent",       C.c_void_p)]

h = C.c_void_p()
if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX), C.byref(h)) != FT_OK:
    sys.exit("FT_Create failed -- is the Ft+ enumerated?")

# --- control writes (synchronous: NULL overlapped) ---------------------------
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

# --- parse args --------------------------------------------------------------
args    = [a.lower() for a in sys.argv[1:]]
verify  = any(a.startswith("v") for a in args)
pattern = PAT_LFSR if "lfsr" in args else PAT_COUNTER
if verify and pattern != PAT_COUNTER:
    print("note: gapless verify only meaningful for the counter pattern")

# --- chip-config dump --------------------------------------------------------
# FT_60XCONFIGURATION is 152 bytes; the fields we care about sit at fixed
# offsets: FIFOClock@137, FIFOMode@138, ChannelConfig@139.
if "cfg" in args:
    cfg = (C.c_ubyte * 152)()
    d3.FT_GetChipConfiguration.restype = C.c_ulong
    st = d3.FT_GetChipConfiguration(h, C.byref(cfg))
    if st != FT_OK:
        sys.exit(f"FT_GetChipConfiguration failed: st={st} ({ft_status(st)})")
    clk  = {0: "100 MHz", 1: "66 MHz"}.get(cfg[137], f"raw={cfg[137]}")
    mode = {0: "245 FIFO mode", 1: "FT600/multi-channel mode"}.get(
        cfg[138], f"raw={cfg[138]}")
    chan = {0: "4 channels", 1: "2 channels", 2: "1 channel",
            3: "1 channel (OUT pipe only)",
            4: "1 channel (IN pipe only)"}.get(cfg[139], f"raw={cfg[139]}")
    print(f"VID:PID        = {cfg[0] | (cfg[1] << 8):04X}:"
          f"{cfg[2] | (cfg[3] << 8):04X}")
    print(f"FIFO clock     = {clk}")
    print(f"FIFO mode      = {mode}      <-- the RTL assumes '245 FIFO mode'")
    print(f"Channel config = {chan}")
    d3.FT_Close(h)
    sys.exit(0)

# --- lock-only diagnostic ----------------------------------------------------
# Send exactly ONE word (the magic) and hold, so you can read the LEDs.
#   Correct behaviour:  LED6 (rx_locked) -> ON,  LED3:0 (cmd_count) -> 0000.
#   The magic is consumed by the lock search, NOT pushed to the decoder, so a
#   single lock word must leave cmd_count at zero.  If cmd_count is NON-zero
#   after one word, the FPGA read the FT601 more than once for that single
#   host write -> the RX latency / capture window is wrong (over-reading),
#   which is the same fault that stalls the OUT pipe in the full run.
if "lock" in args:
    print("LOCK-ONLY: sending a single 0xA5A55A5A, then holding.")
    print("  expect  LED7 ft_locked = ON")
    print("          LED6 rx_locked = ON   (magic found)")
    print("          LED3:0 cmd_count = 0  (magic is NOT counted as a command)")
    print("  if LED3:0 is non-zero after one word -> FPGA is over-reading.")
    send_cmd(LOCK_WORD, "lock")
    print("sent. Read the LEDs now. Ctrl-C to exit (FPGA left as-is).")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        d3.FT_Close(h)
    sys.exit(0)

# --- bring-up sequence -------------------------------------------------------
print("locking RX window (0xA5A55A5A)...")
send_cmd(LOCK_WORD, "lock")             # MUST be first after FPGA reset
time.sleep(0.05)

send_cmd(cmd(OP_SET_PAT, pattern), "set_pat")
send_cmd(cmd(OP_RST_CNT), "rst_cnt")    # zero counter (implies STOP)

# *** The call that matters. Without it: ~40MB/s and a wrong conclusion.
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

send_cmd(cmd(OP_START), "start")        # arm reads first, THEN start streaming

expect = None
total = window = 0
gap_events = missing = dups = rewinds = 0
loss_hist = {}          # words-lost-per-event -> count (tells us replay depth)
n  = C.c_ulong(0)
t0 = time.perf_counter()
print("streaming%s...  (Ctrl-C to stop)" % (" (verifying)" if verify else ""))

def check(w):
    """Classify discontinuities: gap (words missing), dup, or rewind."""
    global gap_events, missing, dups, rewinds
    d = np.diff(w.astype(np.int64))
    d = d[d != -(2**32 - 1)]                # 32-bit counter wrap is legal
    dups    += int(np.count_nonzero(d == 0))
    rewinds += int(np.count_nonzero(d < 0))
    gm = d > 1
    ge = int(np.count_nonzero(gm))
    gap_events += ge
    if ge:
        lost = (d[gm] - 1)
        missing += int(lost.sum())
        for v, c in zip(*np.unique(lost, return_counts=True)):
            loss_hist[int(v)] = loss_hist.get(int(v), 0) + int(c)

try:
    while True:
        for i in range(NBUF):
            if d3.FT_GetOverlappedResult(h, C.byref(ovs[i]), C.byref(n),
                                         C.c_int(1)) != FT_OK:
                raise RuntimeError("read error")
            nb = n.value
            if verify and nb >= 4:
                w = views[i][:nb // 4]
                if expect is not None and w[0] != expect:
                    check(np.array([expect - 1, w[0]], dtype=np.uint32))
                check(w)
                expect = np.uint32(w[-1] + 1)
            total += nb; window += nb
            queue(i)

        dt = time.perf_counter() - t0
        if dt >= 1.0:
            print(f"{window/dt/1e6:7.1f} MB/s   total {total/1e9:7.2f} GB   "
                  f"gap_events {gap_events}  missing {missing}  "
                  f"dups {dups}  rewinds {rewinds}")
            if loss_hist:
                print(f"          words lost per event: "
                      f"{dict(sorted(loss_hist.items())[:8])}")
            window, t0 = 0, time.perf_counter()
except KeyboardInterrupt:
    pass
finally:
    send_cmd(cmd(OP_STOP), "stop")      # halt the pattern source
    for i in range(NBUF):
        d3.FT_ReleaseOverlapped(h, C.byref(ovs[i]))
    d3.FT_Close(h)
