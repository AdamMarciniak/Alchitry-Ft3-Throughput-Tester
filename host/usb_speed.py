"""What speed did the FT601 actually enumerate at?

45 MB/s is what USB 2.0 High Speed delivers after bulk overhead (480 Mbps raw);
a trained SuperSpeed link does 300+.  So before profiling any host code, settle
which link you have.  bcdUSB in the device descriptor is the authoritative
answer - 0x0300 means the SuperSpeed link trained, 0x0200 means it fell back.

The classic cause of a silent fallback is the CABLE: the Ft+ uses a USB 3
Micro-B socket, and an ordinary USB 2 Micro-B plug fits the narrow half of it
perfectly well.  It will work, and it will be capped at exactly this speed.

Run with nothing else holding the device open:   python usb_speed.py
"""
import ctypes as C, os, sys

FT_OK, FT_OPEN_BY_INDEX = 0, 0x10
FT_FLAGS_OPENED, FT_FLAGS_HISPEED, FT_FLAGS_SUPERSPEED = 1, 2, 4

class DevInfo(C.Structure):
    _fields_ = [("Flags", C.c_ulong), ("Type", C.c_ulong), ("ID", C.c_ulong),
                ("LocId", C.c_ulong), ("SerialNumber", C.c_char * 16),
                ("Description", C.c_char * 32), ("ftHandle", C.c_void_p)]

class DevDesc(C.Structure):
    _pack_ = 1
    _fields_ = [("bLength", C.c_ubyte), ("bDescriptorType", C.c_ubyte),
                ("bcdUSB", C.c_ushort), ("bDeviceClass", C.c_ubyte),
                ("bDeviceSubClass", C.c_ubyte), ("bDeviceProtocol", C.c_ubyte),
                ("bMaxPacketSize0", C.c_ubyte), ("idVendor", C.c_ushort),
                ("idProduct", C.c_ushort), ("bcdDevice", C.c_ushort),
                ("iManufacturer", C.c_ubyte), ("iProduct", C.c_ubyte),
                ("iSerialNumber", C.c_ubyte), ("bNumConfigurations", C.c_ubyte)]

d3 = C.WinDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "FTD3XX.dll"))
for f in ("FT_CreateDeviceInfoList", "FT_GetDeviceInfoList", "FT_Create",
          "FT_Close", "FT_GetDeviceDescriptor"):
    getattr(d3, f).restype = C.c_ulong

n = C.c_ulong(0)
if d3.FT_CreateDeviceInfoList(C.byref(n)) != FT_OK or n.value == 0:
    sys.exit("no FT60x enumerated - check the cable and that it is plugged in.")
arr = (DevInfo * n.value)()
d3.FT_GetDeviceInfoList(arr, C.byref(n))
busy = False
for i in range(n.value):
    fl = arr[i].Flags
    tag = ("SuperSpeed" if fl & FT_FLAGS_SUPERSPEED else
           "HighSpeed"  if fl & FT_FLAGS_HISPEED else "not reported")
    print(f"[{i}] flags=0x{fl:X} open={bool(fl & FT_FLAGS_OPENED)} speed={tag}")
    busy |= bool(fl & FT_FLAGS_OPENED)
if busy:
    print("\nDevice is OPEN in another process - close tfm_gl_host / ft601_host "
          "and\nre-run, or the descriptor read below cannot happen.")

h = C.c_void_p()
if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX), C.byref(h)) != FT_OK:
    sys.exit("FT_Create failed (device busy or driver problem).")
dd = DevDesc()
st = d3.FT_GetDeviceDescriptor(h, C.byref(dd))
d3.FT_Close(h)
if st != FT_OK:
    sys.exit(f"FT_GetDeviceDescriptor failed: st={st}")

print(f"\nVID:PID   {dd.idVendor:04X}:{dd.idProduct:04X}")
print(f"bcdUSB    0x{dd.bcdUSB:04X}")
print(f"EP0 size  {dd.bMaxPacketSize0}   (9 = 2^9 = 512, SuperSpeed; "
      f"64 = High Speed)")
if dd.bcdUSB >= 0x0300:
    print("\n==> SuperSpeed link. The 45 MB/s cap is NOT the USB link - "
          "look at the host code.")
else:
    print("\n==> USB 2.0 HIGH SPEED. This is the 45 MB/s cap, and no amount of\n"
          "    host optimisation will move it. In order of likelihood:\n"
          "      1. USB 2 Micro-B cable in the Ft+'s USB 3 Micro-B socket\n"
          "         (fits the narrow half; works; caps at exactly this speed)\n"
          "      2. damaged/marginal USB 3 cable - SuperSpeed pairs not mating\n"
          "      3. front-panel port or hub wired to a 2.0 header\n"
          "      4. connector not fully seated in the wide half")
