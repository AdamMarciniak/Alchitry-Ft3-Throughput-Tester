"""Live USB link-speed watcher for the FT601.

Leave this running and hot-swap cables and ports; it prints a line whenever the
device appears, disappears, or changes negotiated speed, so a bisection takes
seconds instead of a re-run each time.

  python usb_watch.py

LocId changes when you move to a different physical port, so it also confirms
you actually landed somewhere new rather than the same port on a different hub.
"""
import ctypes as C, os, sys, time

FT_FLAGS_OPENED, FT_FLAGS_HISPEED, FT_FLAGS_SUPERSPEED = 1, 2, 4

class DevInfo(C.Structure):
    _fields_ = [("Flags", C.c_ulong), ("Type", C.c_ulong), ("ID", C.c_ulong),
                ("LocId", C.c_ulong), ("SerialNumber", C.c_char * 16),
                ("Description", C.c_char * 32), ("ftHandle", C.c_void_p)]

d3 = C.WinDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "FTD3XX.dll"))
d3.FT_CreateDeviceInfoList.restype = C.c_ulong
d3.FT_GetDeviceInfoList.restype = C.c_ulong

def state():
    n = C.c_ulong(0)
    if d3.FT_CreateDeviceInfoList(C.byref(n)) != 0 or n.value == 0:
        return None
    arr = (DevInfo * n.value)()
    if d3.FT_GetDeviceInfoList(arr, C.byref(n)) != 0:
        return None
    f = arr[0].Flags
    speed = ("SUPERSPEED" if f & FT_FLAGS_SUPERSPEED else
             "high speed (USB 2.0)" if f & FT_FLAGS_HISPEED else
             f"unreported (0x{f:X})")
    return speed, arr[0].LocId, bool(f & FT_FLAGS_OPENED)

print("watching FT601 link speed - swap cables/ports, Ctrl-C to stop\n")
prev, t0 = "init", time.time()
try:
    while True:
        s = state()
        cur = "ABSENT" if s is None else f"{s[0]}  LocId=0x{s[1]:X}"
        if cur != prev:
            mark = "" if s is None else ("   <<< THIS IS THE ONE"
                                         if "SUPER" in s[0] else "   (still capped ~45 MB/s)")
            print(f"[{time.time()-t0:7.1f}s] {cur}{mark}")
            prev = cur
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nstopped.")
