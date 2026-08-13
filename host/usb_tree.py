"""List every USB device on this machine with its NEGOTIATED link speed.

Asks the Windows USB hub driver directly (IOCTL_USB_GET_NODE_CONNECTION_
INFORMATION_EX), so it works for any device - phone, flash drive, FT601 - and
does not depend on FTD3XX.  Useful for proving whether a given port and cable
can do SuperSpeed at all: plug in something known-good and look.

  python usb_tree.py
"""
import ctypes as C
from ctypes import wintypes as W

SPEEDS = {0: "Low (1.5 Mbps)", 1: "Full (12 Mbps)",
          2: "High / USB 2.0 (480 Mbps)", 3: "SUPERSPEED / USB 3.x (5+ Gbps)"}

IOCTL_USB_GET_NODE_INFORMATION = 0x220408
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX = 0x220448
# Every physical USB 3 connector appears TWICE on an xHCI root hub: once as a
# USB 2.0 port and once as a SuperSpeed port, and the two know about each other
# through CompanionPortNumber.  So a USB 2.0 port with a non-zero companion is
# a socket that IS wired for SuperSpeed and simply failed to train - while a
# companion of 0 means that socket is USB 2.0 only, which is what a disabled
# xHCI/USB3 BIOS option or a 2.0-only header looks like from here.
IOCTL_USB_GET_PORT_CONNECTOR_PROPERTIES = 0x220458      # function 278
# EX_V2 is meant to separate CAPABILITY from OPERATION: whether the attached
# device COULD have run at SuperSpeed, not just what it settled for.  Function
# 279 is the right code (274/276/277/278 around it all answer as documented),
# but USBHUB3 here returns ERROR_INVALID_PARAMETER for every port at every
# buffer size, so treat it as optional and never let it decide the verdict.
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2 = 0x22045C   # function 279
GENERIC_WRITE, FILE_SHARE_WRITE, OPEN_EXISTING = 0x40000000, 2, 3
INVALID_HANDLE = C.c_void_p(-1).value
DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x02, 0x10

class GUID(C.Structure):
    _fields_ = [("D1", C.c_ulong), ("D2", C.c_ushort), ("D3", C.c_ushort),
                ("D4", C.c_ubyte * 8)]

# GUID_DEVINTERFACE_USB_HUB
HUB_GUID = GUID(0xF18A0E88, 0xC30C, 0x11D0,
                (C.c_ubyte * 8)(0x88, 0x15, 0x00, 0xA0, 0xC9, 0x06, 0xBE, 0xD8))

class SP_DEVICE_INTERFACE_DATA(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", W.DWORD), ("Reserved", C.POINTER(C.c_ulong))]

class USB_DEVICE_DESCRIPTOR(C.Structure):
    _pack_ = 1
    _fields_ = [("bLength", C.c_ubyte), ("bDescriptorType", C.c_ubyte),
                ("bcdUSB", C.c_ushort), ("bDeviceClass", C.c_ubyte),
                ("bDeviceSubClass", C.c_ubyte), ("bDeviceProtocol", C.c_ubyte),
                ("bMaxPacketSize0", C.c_ubyte), ("idVendor", C.c_ushort),
                ("idProduct", C.c_ushort), ("bcdDevice", C.c_ushort),
                ("iManufacturer", C.c_ubyte), ("iProduct", C.c_ubyte),
                ("iSerialNumber", C.c_ubyte), ("bNumConfigurations", C.c_ubyte)]

# pack(1), as usbioctl.h declares it.  Everything up to Speed is byte-aligned
# either way, so a wrongly-unpacked version still reports the right speed and
# VID - and then silently misreads ConnectionStatus by one byte, which is how
# this presented: correct devices, all filtered out as "not connected".
class NODE_CONN_INFO_EX(C.Structure):
    _pack_ = 1
    _fields_ = [("ConnectionIndex", C.c_ulong),
                ("DeviceDescriptor", USB_DEVICE_DESCRIPTOR),
                ("CurrentConfigurationValue", C.c_ubyte), ("Speed", C.c_ubyte),
                ("DeviceIsHub", C.c_ubyte), ("DeviceAddress", C.c_ushort),
                ("NumberOfOpenPipes", C.c_ulong), ("ConnectionStatus", C.c_ulong),
                ("PipeList", C.c_ubyte * 96)]

class USB_HUB_DESCRIPTOR(C.Structure):
    _pack_ = 1
    _fields_ = [("bDescriptorLength", C.c_ubyte), ("bDescriptorType", C.c_ubyte),
                ("bNumberOfPorts", C.c_ubyte), ("wHubCharacteristics", C.c_ushort),
                ("bPowerOnToPowerGood", C.c_ubyte), ("bHubControlCurrent", C.c_ubyte),
                ("bRemoveAndPowerMask", C.c_ubyte * 64)]

class USB_NODE_INFORMATION(C.Structure):
    _fields_ = [("NodeType", C.c_ulong), ("HubDescriptor", USB_HUB_DESCRIPTOR),
                ("HubIsBusPowered", C.c_ubyte)]

class NODE_CONN_INFO_EX_V2(C.Structure):
    _pack_ = 1
    _fields_ = [("ConnectionIndex", C.c_ulong), ("Length", C.c_ulong),
                ("SupportedUsbProtocols", C.c_ulong), ("Flags", C.c_ulong)]

class PORT_CONNECTOR_PROPERTIES(C.Structure):
    _pack_ = 1
    _fields_ = [("ConnectionIndex", C.c_ulong), ("ActualLength", C.c_ulong),
                ("UsbPortProperties", C.c_ulong),
                ("CompanionIndex", C.c_ushort),
                ("CompanionPortNumber", C.c_ushort),
                ("CompanionHubSymbolicLinkName", C.c_wchar * 260)]

setup, k32 = C.windll.setupapi, C.windll.kernel32
# HDEVINFO and HANDLE are pointers: without explicit restypes ctypes truncates
# them to 32-bit ints on a 64-bit build and every subsequent call fails.
k32.CreateFileW.restype = C.c_void_p
setup.SetupDiGetClassDevsW.restype = C.c_void_p
setup.SetupDiGetClassDevsW.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p,
                                       W.DWORD]
setup.SetupDiEnumDeviceInterfaces.argtypes = [C.c_void_p, C.c_void_p,
                                              C.c_void_p, W.DWORD, C.c_void_p]
setup.SetupDiGetDeviceInterfaceDetailW.argtypes = [C.c_void_p, C.c_void_p,
                                                   C.c_void_p, W.DWORD,
                                                   C.c_void_p, C.c_void_p]
setup.SetupDiDestroyDeviceInfoList.argtypes = [C.c_void_p]

def hub_paths():
    h = setup.SetupDiGetClassDevsW(C.byref(HUB_GUID), None, None,
                                   DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not h or h == INVALID_HANDLE:
        return []
    out, i = [], 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = C.sizeof(did)
        if not setup.SetupDiEnumDeviceInterfaces(h, None, C.byref(HUB_GUID), i,
                                                 C.byref(did)):
            break
        need = W.DWORD(0)
        setup.SetupDiGetDeviceInterfaceDetailW(h, C.byref(did), None, 0,
                                               C.byref(need), None)
        if need.value:
            buf = C.create_string_buffer(need.value)
            C.cast(buf, C.POINTER(W.DWORD))[0] = (
                8 if C.sizeof(C.c_void_p) == 8 else 6)
            if setup.SetupDiGetDeviceInterfaceDetailW(h, C.byref(did), buf,
                                                      need.value, None, None):
                out.append(C.wstring_at(C.addressof(buf) + C.sizeof(W.DWORD)))
        i += 1
    setup.SetupDiDestroyDeviceInfoList(h)
    return out

def scan():
    rows = []
    for p in hub_paths():
        # Both root hubs are literally named "root_hub30"; without the
        # instance id they collide and one silently replaces the other.
        parts = p.split("#")
        short = "#".join(parts[1:3]) if len(parts) > 2 else p
        hh = k32.CreateFileW(p, GENERIC_WRITE, FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
        if not hh or hh == INVALID_HANDLE:
            continue
        ni, ret = USB_NODE_INFORMATION(), W.DWORD()
        if k32.DeviceIoControl(C.c_void_p(hh), IOCTL_USB_GET_NODE_INFORMATION,
                               C.byref(ni), C.sizeof(ni), C.byref(ni),
                               C.sizeof(ni), C.byref(ret), None):
            for port in range(1, ni.HubDescriptor.bNumberOfPorts + 1):
                ci = NODE_CONN_INFO_EX()
                ci.ConnectionIndex = port
                if not k32.DeviceIoControl(
                        C.c_void_p(hh),
                        IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX,
                        C.byref(ci), C.sizeof(ci), C.byref(ci), C.sizeof(ci),
                        C.byref(ret), None):
                    continue
                d = ci.DeviceDescriptor
                if ci.ConnectionStatus != 1 or d.idVendor == 0:
                    continue                    # nothing connected
                v2 = NODE_CONN_INFO_EX_V2()
                v2.ConnectionIndex, v2.Length = port, C.sizeof(v2)
                cap_ss = None
                if k32.DeviceIoControl(
                        C.c_void_p(hh),
                        IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2,
                        C.byref(v2), C.sizeof(v2), C.byref(v2), C.sizeof(v2),
                        C.byref(ret), None):
                    cap_ss = bool(v2.Flags & 0x2)   # SuperSpeedCapableOrHigher
                # ci.Speed SATURATES AT 2 (UsbHighSpeed) - a device that is
                # demonstrably running SuperSpeed still reports 2 here, which is
                # what made this script call a healthy 5 Gbps link "USB 2.0".
                # bMaxPacketSize0 is the honest witness: the spec makes SS
                # devices encode EP0 as the EXPONENT (9 -> 2^9 = 512), while
                # High/Full/Low report the literal byte count (64/64/8).  A
                # literal 9 is not a legal packet size, so 9 means SuperSpeed.
                sp = 3 if d.bMaxPacketSize0 == 9 else ci.Speed
                rows.append((short, port, d.idVendor, d.idProduct, sp,
                             d.bcdUSB, bool(ci.DeviceIsHub), cap_ss))
            nports[short] = ni.HubDescriptor.bNumberOfPorts
            # Which sockets on this hub are physically wired for SuperSpeed?
            cap = []
            for port in range(1, ni.HubDescriptor.bNumberOfPorts + 1):
                pc = PORT_CONNECTOR_PROPERTIES()
                pc.ConnectionIndex = port
                if k32.DeviceIoControl(
                        C.c_void_p(hh), IOCTL_USB_GET_PORT_CONNECTOR_PROPERTIES,
                        C.byref(pc), C.sizeof(pc), C.byref(pc), C.sizeof(pc),
                        C.byref(ret), None):
                    cap.append((port, pc.CompanionPortNumber,
                                bool(pc.UsbPortProperties & 0x1),      # connectable
                                bool(pc.UsbPortProperties & 0x8)))     # Type-C
            conn[short] = cap
        k32.CloseHandle(C.c_void_p(hh))
    return rows

nports, conn = {}, {}
rows = scan()
if not rows:
    print("no devices found (try running from an elevated prompt)")
else:
    seen = set(r[0] for r in rows)
    for h in nports:
        if h not in seen:
            print(f"\n{h}   ({nports[h]} ports)  - nothing attached")
    # Which (hub, port) pairs are the 2.0 half of a socket that IS wired for
    # SuperSpeed?  Landing there is how a fallback looks from the host side.
    paired = {(h, c[0]) for h, cap in conn.items() for c in cap if c[1]}

    def fell_back(hub, port, sp, bcd):
        # Only a USB 3 device sitting on an SS-wired socket at 2.0 speed is a
        # failed link.  A real USB 2.0 device belongs there and reports bcdUSB
        # 0x0200; a USB 3 device forced onto the 2.0 pairs must report 0x0210
        # or higher, because it still has to advertise its BOS descriptor.
        return sp != 3 and (hub, port) in paired and bcd >= 0x0210

    last = None
    for hub, port, vid, pid, sp, bcd, isHub, capss in sorted(rows):
        if hub != last:
            print(f"\n{hub}   ({nports.get(hub,'?')} ports)")
            last = hub
        mark = ("   <<< SUPERSPEED" if sp == 3 else
                "   *** USB 3 DEVICE RUNNING AT USB 2.0 - LINK DID NOT TRAIN ***"
                if fell_back(hub, port, sp, bcd) else "")
        print(f"   port {port:<3} {vid:04X}:{pid:04X}  bcdUSB 0x{bcd:04X}  "
              f"{'HUB ' if isHub else '    '}{SPEEDS.get(sp, sp)}{mark}")
    for hub, cap in conn.items():
        pair = [c for c in cap if c[1]]
        print(f"\n{hub}: {len(pair)} of {len(cap)} ports are wired for "
              f"SuperSpeed (have a companion port)")
        if pair:
            for port, comp, usr, tc in pair:
                where = [r for r in rows if r[0] == hub and r[1] == port]
                who = (f"  <- {where[0][2]:04X}:{where[0][3]:04X} is here"
                       if where else "")
                print(f"    port {port:<3} <-> companion {comp:<3}"
                      f"{'  Type-C' if tc else ''}{who}")
        else:
            print("    NONE. Every socket on this hub is USB 2.0 only - that is "
                  "what a\n    disabled xHCI/USB3 BIOS option or a 2.0-only "
                  "front header looks like.")
    ss = [r for r in rows if r[4] == 3 and not r[6]]
    stuck = [r for r in rows if fell_back(r[0], r[1], r[4], r[5])]
    print(f"\n{len(ss)} non-hub device(s) negotiated SuperSpeed on this machine.")
    for hub, port, vid, pid, sp, bcd, isHub, capss in ss:
        print(f"   {vid:04X}:{pid:04X} on {hub} port {port}")
    if stuck:
        print(f"\n{len(stuck)} USB 3 device(s) FELL BACK to USB 2.0:")
        for hub, port, vid, pid, sp, bcd, isHub, capss in stuck:
            print(f"   {vid:04X}:{pid:04X} on {hub} port {port}  "
                  f"(bcdUSB 0x{bcd:04X})")
        print("   In order of likelihood: USB 2 cable in a USB 3 socket, a\n"
              "   marginal/damaged USB 3 cable, a front-panel port on a 2.0\n"
              "   header, or the plug not fully seated in the wide half.")
    elif not ss:
        print("NOTHING is at SuperSpeed - but nothing USB 3 is plugged in either,\n"
              "so this proves nothing about the ports.  Plug in a known USB 3\n"
              "device (flash drive, external SSD) and re-run.")
