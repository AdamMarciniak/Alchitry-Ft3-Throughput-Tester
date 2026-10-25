#!/usr/bin/env python3
"""AFE5804 LVDS eye calibration tool for the Alchitry receiver.

The current FPGA UART monitor provides everything needed for a useful bench
calibration without rebuilding the bitstream:

* ``+``/``-`` step the OUT1 IDELAY tap.
* ``>``/``<`` step the FCLK IDELAY tap.
* ``r`` captures 32 raw ISERDES words.
* ``d`` and ``s`` enable the AFE deskew and sync patterns.
* ``S`` issues one common ISERDES BITSLIP.
* ``C`` captures 8192 assembled samples for ramp validation.

This program deliberately does not trust the FPGA's old "data stayed
constant" eye metric.  DATA passes only for the exact deskew codes 0x15/0x2A,
FCLK passes only for a clean 0x00/0x3F alternation, and the two lanes are
scanned and centred independently.

Run this with the imaging program closed and the pulser stopped.  Selected
taps live in the FPGA and are lost on reset; the JSON report records values
that can later be made into RTL defaults once they are repeatable.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
from typing import Optional, Sequence


BAUD_DEFAULT = 2_000_000
N_TAPS = 32
RAW_WORDS = 32
DEEP_SAMPLES = 8192
TAP_PS_APPROX = 78
DESKEW_CODES = frozenset((0x15, 0x2A))
SYNC_CODES = frozenset((0x00, 0x3F))


class EyeToolError(RuntimeError):
    """Expected calibration or protocol failure."""


class SerialTimeout(EyeToolError):
    """The FPGA did not return the requested bytes before the deadline."""


@dataclass(frozen=True)
class EyeWindow:
    start: int
    end: int
    width: int
    center: int
    margin: int
    touches_edge: bool


@dataclass
class TapScore:
    tap: int
    observations: int
    errors: int
    details: dict[str, int]

    @property
    def passed(self) -> bool:
        return self.errors == 0


@dataclass
class CalibrationReport:
    timestamp: str
    port: str
    baud: int
    scan_captures: int
    validation_captures: int
    minimum_eye_taps: int
    guard_taps: int
    initial_fpga_map: str
    initial_fpga_tap: int
    fclk_scores: list[dict]
    data_scores: list[dict]
    fclk_window: Optional[dict]
    data_window: Optional[dict]
    fclk_tap: Optional[int]
    data_tap: Optional[int]
    bitslips: Optional[int]
    sync_errors: Optional[int]
    ramp_errors: Optional[int]
    passed: bool
    notes: list[str]


def _word(fclk: int, data: int) -> int:
    """Pack the two six-bit lanes like afe_rx.v's raw capture buffer."""
    return ((fclk & 0x3F) << 8) | (data & 0x3F)


def split_raw(words: Sequence[int]) -> tuple[list[int], list[int]]:
    fclk = [((word >> 8) & 0x3F) for word in words]
    data = [(word & 0x3F) for word in words]
    return fclk, data


def score_fclk_blocks(blocks: Sequence[Sequence[int]], tap: int = -1) -> TapScore:
    invalid = 0
    repeat = 0
    missing_level = 0
    observations = 0
    for words in blocks:
        fclk, _ = split_raw(words)
        observations += len(fclk)
        invalid += sum(value not in SYNC_CODES for value in fclk)
        repeat += sum(a == b for a, b in zip(fclk, fclk[1:]))
        if fclk and not ({0x00, 0x3F} <= set(fclk)):
            missing_level += 1
    errors = invalid + repeat + missing_level
    return TapScore(tap, observations, errors,
                    {"invalid_codes": invalid,
                     "non_alternating_edges": repeat,
                     "captures_missing_a_level": missing_level})


def score_data_blocks(blocks: Sequence[Sequence[int]], tap: int = -1) -> TapScore:
    invalid = 0
    changes = 0
    fclk_errors = 0
    observations = 0
    first_data: Optional[int] = None
    for words in blocks:
        fclk, data = split_raw(words)
        observations += len(data)
        invalid += sum(value not in DESKEW_CODES for value in data)
        changes += sum(a != b for a, b in zip(data, data[1:]))
        if data:
            if first_data is None:
                first_data = data[0]
            elif data[0] != first_data:
                changes += 1
        # The previously trained frame lane must remain healthy throughout the
        # data scan; otherwise a DATA result is not trustworthy.
        fscore = score_fclk_blocks((words,))
        fclk_errors += fscore.errors
    errors = invalid + changes + fclk_errors
    return TapScore(tap, observations, errors,
                    {"invalid_codes": invalid,
                     "deskew_code_changes": changes,
                     "fclk_errors": fclk_errors})


def score_sync_blocks(blocks: Sequence[Sequence[int]]) -> TapScore:
    """Validate word alignment after BITSLIP.

    Depending on AFE bit order the sync data can be in phase with FCLK or its
    complement.  Both are legitimate; a shifted word is not.  The relation
    must remain constant throughout every capture.
    """
    invalid_fclk = 0
    invalid_data = 0
    fclk_repeat = 0
    data_repeat = 0
    relation_errors = 0
    observations = 0
    expected_relation: Optional[int] = None
    for words in blocks:
        fclk, data = split_raw(words)
        observations += len(words)
        invalid_fclk += sum(value not in SYNC_CODES for value in fclk)
        invalid_data += sum(value not in SYNC_CODES for value in data)
        fclk_repeat += sum(a == b for a, b in zip(fclk, fclk[1:]))
        data_repeat += sum(a == b for a, b in zip(data, data[1:]))
        for fv, dv in zip(fclk, data):
            relation = fv ^ dv
            if relation not in (0x00, 0x3F):
                relation_errors += 1
            elif expected_relation is None:
                expected_relation = relation
            elif relation != expected_relation:
                relation_errors += 1
    errors = (invalid_fclk + invalid_data + fclk_repeat + data_repeat +
              relation_errors)
    return TapScore(-1, observations, errors,
                    {"invalid_fclk_codes": invalid_fclk,
                     "invalid_data_codes": invalid_data,
                     "fclk_non_alternating_edges": fclk_repeat,
                     "data_non_alternating_edges": data_repeat,
                     "changing_lane_relation": relation_errors})


def ramp_error_count(samples: Sequence[int]) -> int:
    values = [sample & 0x0FFF for sample in samples]
    return sum((((b - a) & 0x0FFF) != 1)
               for a, b in zip(values, values[1:]))


def find_eye(scores: Sequence[TapScore], minimum: int, guard: int) -> Optional[EyeWindow]:
    """Choose the best complete, linear zero-error run.

    Tap 31 and tap 0 are not joined.  A run touching either scan boundary is
    reported as clipped because its true edge was not observed.  A complete
    run wins a width tie over a clipped run, then proximity to the middle of
    the IDELAY range breaks the remaining tie.
    """
    runs: list[tuple[int, int]] = []
    start: Optional[int] = None
    for tap in range(N_TAPS + 1):
        passed = tap < len(scores) and scores[tap].passed
        if passed and start is None:
            start = tap
        elif not passed and start is not None:
            runs.append((start, tap - 1))
            start = None

    candidates: list[EyeWindow] = []
    for lo, hi in runs:
        width = hi - lo + 1
        center = lo + (width - 1) // 2
        margin = min(center - lo, hi - center)
        if width >= minimum and margin >= guard:
            candidates.append(EyeWindow(lo, hi, width, center, margin,
                                        lo == 0 or hi == N_TAPS - 1))
    if not candidates:
        return None
    candidates.sort(key=lambda window: (window.width,
                                        not window.touches_edge,
                                        -abs(window.center - 15.5)),
                    reverse=True)
    return candidates[0]


def eye_map(scores: Sequence[TapScore]) -> str:
    return "".join("#" if score.passed else "." for score in scores)


class _WinDCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("Flags", wintypes.DWORD),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", wintypes.BYTE),
        ("Parity", wintypes.BYTE),
        ("StopBits", wintypes.BYTE),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class _WinTimeouts(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


class NativeWindowsSerial:
    """Small dependency-free synchronous COM-port backend."""

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    PURGE_TXCLEAR = 0x0004
    PURGE_RXCLEAR = 0x0008

    def __init__(self, port: str, baud: int):
        if os.name != "nt":
            raise EyeToolError("pyserial is required on non-Windows systems")
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()
        name = port if port.startswith("\\\\.\\") else "\\\\.\\" + port
        self._handle = self._k32.CreateFileW(
            name, self.GENERIC_READ | self.GENERIC_WRITE, 0, None,
            self.OPEN_EXISTING, 0, None)
        invalid = wintypes.HANDLE(-1).value
        if self._handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._k32.SetupComm(self._handle, 65536, 65536):
                raise ctypes.WinError(ctypes.get_last_error())
            dcb = _WinDCB()
            dcb.DCBlength = ctypes.sizeof(_WinDCB)
            if not self._k32.GetCommState(self._handle, ctypes.byref(dcb)):
                raise ctypes.WinError(ctypes.get_last_error())
            dcb.BaudRate = baud
            # fBinary, DTR enable and RTS enable; hardware/software flow off.
            dcb.Flags = 0x00001011
            dcb.ByteSize = 8
            dcb.Parity = 0
            dcb.StopBits = 0
            if not self._k32.SetCommState(self._handle, ctypes.byref(dcb)):
                raise ctypes.WinError(ctypes.get_last_error())
            timeouts = _WinTimeouts(0, 0, 100, 0, 1000)
            if not self._k32.SetCommTimeouts(self._handle,
                                            ctypes.byref(timeouts)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.reset_input_buffer()
        except Exception:
            self.close()
            raise

    def _configure_signatures(self) -> None:
        k32 = self._k32
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.SetupComm.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                  wintypes.DWORD]
        k32.GetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(_WinDCB)]
        k32.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(_WinDCB)]
        k32.SetCommTimeouts.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(_WinTimeouts)]
        k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                 wintypes.LPVOID]
        k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                  wintypes.LPVOID]
        k32.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def reset_input_buffer(self) -> None:
        if not self._k32.PurgeComm(self._handle,
                                   self.PURGE_RXCLEAR | self.PURGE_TXCLEAR):
            raise ctypes.WinError(ctypes.get_last_error())

    def write(self, payload: bytes) -> int:
        buf = ctypes.create_string_buffer(payload)
        count = wintypes.DWORD()
        if not self._k32.WriteFile(self._handle, buf, len(payload),
                                   ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(count.value)

    def read(self, size: int) -> bytes:
        buf = ctypes.create_string_buffer(max(1, size))
        count = wintypes.DWORD()
        if not self._k32.ReadFile(self._handle, buf, size,
                                  ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw[:count.value]

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle not in (None, wintypes.HANDLE(-1).value):
            self._k32.CloseHandle(handle)
            self._handle = None


class PySerialBackend:
    def __init__(self, port: str, baud: int):
        import serial  # type: ignore
        self._serial = serial.Serial(port, baudrate=baud, bytesize=8,
                                     parity="N", stopbits=1,
                                     timeout=0.1, write_timeout=1.0)
        self.reset_input_buffer()

    def reset_input_buffer(self) -> None:
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def write(self, payload: bytes) -> int:
        return int(self._serial.write(payload))

    def read(self, size: int) -> bytes:
        return bytes(self._serial.read(size))

    def close(self) -> None:
        self._serial.close()


def open_serial(port: str, baud: int):
    try:
        import serial  # noqa: F401  # type: ignore
    except ImportError:
        return NativeWindowsSerial(port, baud)
    return PySerialBackend(port, baud)


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports  # type: ignore
        return sorted((item.device, item.description) for item in list_ports.comports())
    except ImportError:
        if os.name != "nt":
            return []
        import winreg
        found: list[tuple[str, str]] = []
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                index = 0
                while True:
                    try:
                        device, port, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    found.append((str(port), str(device)))
                    index += 1
        except FileNotFoundError:
            pass
        return sorted(found)


class AfeMonitor:
    def __init__(self, backend):
        self.backend = backend
        self.rx = bytearray()
        self.data_tap = 0
        self.fclk_tap = 0

    def close(self) -> None:
        self.backend.close()

    def write(self, payload: bytes) -> None:
        count = self.backend.write(payload)
        if count != len(payload):
            raise EyeToolError(f"short serial write: {count}/{len(payload)} bytes")

    def _fill(self, minimum: int, deadline: float) -> None:
        while len(self.rx) < minimum:
            if time.monotonic() >= deadline:
                raise SerialTimeout(f"serial timeout after receiving {len(self.rx)} bytes")
            chunk = self.backend.read(max(256, minimum - len(self.rx)))
            if chunk:
                self.rx.extend(chunk)

    def read_exact(self, count: int, timeout: float = 2.0) -> bytes:
        deadline = time.monotonic() + timeout
        self._fill(count, deadline)
        payload = bytes(self.rx[:count])
        del self.rx[:count]
        return payload

    def readline(self, timeout: float = 2.0) -> bytes:
        deadline = time.monotonic() + timeout
        while True:
            end = self.rx.find(b"\n")
            if end >= 0:
                payload = bytes(self.rx[:end + 1])
                del self.rx[:end + 1]
                return payload
            self._fill(len(self.rx) + 1, deadline)

    def command_echo(self, command: str, timeout: float = 2.0) -> None:
        self.write(command.encode("ascii"))
        expected = command[0].encode("ascii")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.readline(max(0.1, deadline - time.monotonic())).strip()
            if line == expected:
                return
        raise SerialTimeout(f"no echo for {command!r}")

    def write_register(self, address: int, value: int) -> None:
        self.command_echo(f"w{address:02X}{value:04X}")

    def pattern_off(self) -> None:
        self.command_echo("n")
        self.write_register(0x25, 0x0000)

    def set_pattern(self, pattern: str) -> None:
        if pattern == "deskew":
            self.write_register(0x25, 0x0000)
            self.command_echo("d")
        elif pattern == "sync":
            self.write_register(0x25, 0x0000)
            self.command_echo("s")
        elif pattern == "ramp":
            self.command_echo("n")
            self.command_echo("m")
        elif pattern == "off":
            self.pattern_off()
        else:
            raise ValueError(f"unknown pattern {pattern!r}")

    def establish_tap_origin(self) -> tuple[str, int]:
        """Use firmware command A to put both taps at a reported absolute tap."""
        self.set_pattern("deskew")
        self.write(b"A")
        line = self.readline(timeout=5.0).decode("ascii", errors="replace").strip()
        match = re.fullmatch(r"([.#]{32})\s+([0-9A-Fa-f]{2})", line)
        if not match:
            raise EyeToolError(f"unexpected FPGA eye-scan response: {line!r}")
        tap = int(match.group(2), 16)
        if not 0 <= tap < N_TAPS:
            raise EyeToolError(f"FPGA returned invalid tap {tap}")
        self.data_tap = tap
        self.fclk_tap = tap
        return match.group(1), tap

    @staticmethod
    def _steps(current: int, target: int) -> tuple[int, int]:
        forward = (target - current) % N_TAPS
        backward = (current - target) % N_TAPS
        return (1, forward) if forward <= backward else (-1, backward)

    def set_data_tap(self, target: int) -> None:
        direction, count = self._steps(self.data_tap, target)
        for _ in range(count):
            self.command_echo("+" if direction > 0 else "-")
        self.data_tap = target

    def set_fclk_tap(self, target: int) -> None:
        direction, count = self._steps(self.fclk_tap, target)
        for _ in range(count):
            self.command_echo(">" if direction > 0 else "<")
        self.fclk_tap = target

    def capture_raw(self) -> list[int]:
        self.write(b"r")
        words: list[int] = []
        for _ in range(RAW_WORDS):
            line = self.readline(timeout=2.0).strip()
            if not re.fullmatch(rb"[0-9A-Fa-f]{4}", line):
                raise EyeToolError(f"bad raw-capture word: {line!r}")
            words.append(int(line, 16))
        return words

    def capture_deep(self) -> list[int]:
        self.write(b"C")
        payload = self.read_exact(DEEP_SAMPLES * 2, timeout=4.0)
        if payload.startswith(b"?\r\n"):
            raise EyeToolError("deep capture timed out; FCLK is probably not aligned")
        return list(struct.unpack(f"<{DEEP_SAMPLES}H", payload))

    def bitslip(self) -> None:
        self.command_echo("S")


def capture_blocks(monitor: AfeMonitor, count: int) -> list[list[int]]:
    return [monitor.capture_raw() for _ in range(count)]


def scan_lane(monitor: AfeMonitor, lane: str, captures: int,
              settle_seconds: float) -> list[TapScore]:
    scores: list[TapScore] = []
    for tap in range(N_TAPS):
        if lane == "fclk":
            monitor.set_fclk_tap(tap)
        elif lane == "data":
            monitor.set_data_tap(tap)
        else:
            raise ValueError(lane)
        time.sleep(settle_seconds)
        blocks = capture_blocks(monitor, captures)
        score = (score_fclk_blocks(blocks, tap) if lane == "fclk"
                 else score_data_blocks(blocks, tap))
        scores.append(score)
        print(f"\r  {lane.upper():5s} tap {tap:02d}/31  "
              f"errors {score.errors:6d}", end="", flush=True)
    print()
    return scores


def _score_dict(score: TapScore) -> dict:
    result = asdict(score)
    result["passed"] = score.passed
    return result


def save_report(report: CalibrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")


def calibrate(monitor: AfeMonitor, args) -> CalibrationReport:
    notes: list[str] = []
    initial_map, initial_tap = monitor.establish_tap_origin()
    print(f"Firmware reference scan: {initial_map}  tap {initial_tap:02d}")

    print("Scanning FCLK with the sync pattern...")
    monitor.set_pattern("sync")
    fclk_scores = scan_lane(monitor, "fclk", args.scan_captures,
                            args.settle_ms / 1000.0)
    fclk_window = find_eye(fclk_scores, args.minimum_eye, args.guard_taps)
    print(f"FCLK: {eye_map(fclk_scores)}")
    if fclk_window is None:
        raise EyeToolError("FCLK has no acceptable zero-error eye")
    monitor.set_fclk_tap(fclk_window.center)
    print(f"FCLK eye {fclk_window.start:02d}-{fclk_window.end:02d}, "
          f"width {fclk_window.width} taps (~{fclk_window.width * TAP_PS_APPROX} ps), "
          f"center {fclk_window.center:02d}")
    if fclk_window.touches_edge:
        notes.append("FCLK eye touches the scan boundary; its width is clipped")

    print("Scanning DATA with the deskew pattern...")
    monitor.set_pattern("deskew")
    data_scores = scan_lane(monitor, "data", args.scan_captures,
                            args.settle_ms / 1000.0)
    data_window = find_eye(data_scores, args.minimum_eye, args.guard_taps)
    print(f"DATA : {eye_map(data_scores)}")
    if data_window is None:
        raise EyeToolError("DATA has no acceptable zero-error eye")
    monitor.set_data_tap(data_window.center)
    print(f"DATA eye {data_window.start:02d}-{data_window.end:02d}, "
          f"width {data_window.width} taps (~{data_window.width * TAP_PS_APPROX} ps), "
          f"center {data_window.center:02d}")
    if data_window.touches_edge:
        notes.append("DATA eye touches the scan boundary; its width is clipped")

    print("Aligning the six-bit word boundary...")
    monitor.set_pattern("sync")
    bitslips: Optional[int] = None
    sync_score: Optional[TapScore] = None
    for attempt in range(13):
        blocks = capture_blocks(monitor, args.validation_captures)
        sync_score = score_sync_blocks(blocks)
        if sync_score.passed:
            bitslips = attempt
            break
        if attempt != 12:
            monitor.bitslip()
            time.sleep(args.settle_ms / 1000.0)
    if bitslips is None or sync_score is None:
        raise EyeToolError("sync pattern did not align after 12 BITSLIPs")
    print(f"Sync aligned after {bitslips} BITSLIP(s); "
          f"{sync_score.observations} raw words, zero errors")

    ramp_errors: Optional[int] = None
    if not args.no_ramp:
        print("Validating assembled samples with the AFE ramp...")
        monitor.set_pattern("ramp")
        samples = monitor.capture_deep()
        ramp_errors = ramp_error_count(samples)
        if ramp_errors:
            raise EyeToolError(f"ramp validation found {ramp_errors} bad increments")
        print(f"Ramp: {len(samples)} samples, zero bad increments")
    else:
        notes.append("Ramp validation was disabled by command-line option")

    return CalibrationReport(
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        port=args.port,
        baud=args.baud,
        scan_captures=args.scan_captures,
        validation_captures=args.validation_captures,
        minimum_eye_taps=args.minimum_eye,
        guard_taps=args.guard_taps,
        initial_fpga_map=initial_map,
        initial_fpga_tap=initial_tap,
        fclk_scores=[_score_dict(score) for score in fclk_scores],
        data_scores=[_score_dict(score) for score in data_scores],
        fclk_window=asdict(fclk_window),
        data_window=asdict(data_window),
        fclk_tap=fclk_window.center,
        data_tap=data_window.center,
        bitslips=bitslips,
        sync_errors=sync_score.errors,
        ramp_errors=ramp_errors,
        passed=True,
        notes=notes,
    )


def choose_port(requested: Optional[str]) -> str:
    if requested:
        return requested
    ports = list_serial_ports()
    if not ports:
        raise EyeToolError("no serial ports found; specify one with --port COMx")
    likely = [(port, description) for port, description in ports
              if any(token in description.lower()
                     for token in ("alchitry", "ftdi", "usb serial", "vcp"))]
    if len(likely) == 1:
        print(f"Using {likely[0][0]} ({likely[0][1]})")
        return likely[0][0]
    listing = "\n".join(f"  {port}: {description}" for port, description in ports)
    raise EyeToolError("select the FPGA USB serial port with --port:\n" + listing)


def build_parser() -> argparse.ArgumentParser:
    default_report = Path(__file__).resolve().parent / "settings" / "afe_eye_latest.json"
    parser = argparse.ArgumentParser(
        description="Scan and align the AFE5804 OUT1/FCLK LVDS eyes.")
    parser.add_argument("--port", help="AFE monitor serial port, for example COM5")
    parser.add_argument("--baud", type=int, default=BAUD_DEFAULT)
    parser.add_argument("--scan-captures", type=int, default=16,
                        help="32-word captures per tap (default: 16)")
    parser.add_argument("--validation-captures", type=int, default=64,
                        help="32-word sync captures after centring (default: 64)")
    parser.add_argument("--minimum-eye", type=int, default=6,
                        help="minimum consecutive passing taps (default: 6)")
    parser.add_argument("--guard-taps", type=int, default=2,
                        help="required taps from centre to either eye edge (default: 2)")
    parser.add_argument("--settle-ms", type=float, default=1.0,
                        help="delay after changing a tap (default: 1 ms)")
    parser.add_argument("--no-ramp", action="store_true",
                        help="skip the final 8192-sample ramp validation")
    parser.add_argument("--report", type=Path, default=default_report,
                        help=f"JSON report path (default: {default_report})")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="confirm the pulser is stopped and imaging host is closed")
    return parser


def validate_args(args) -> None:
    if args.scan_captures < 1:
        raise EyeToolError("--scan-captures must be at least 1")
    if args.validation_captures < 1:
        raise EyeToolError("--validation-captures must be at least 1")
    if not 1 <= args.minimum_eye <= N_TAPS:
        raise EyeToolError("--minimum-eye must be between 1 and 32")
    if not 0 <= args.guard_taps < N_TAPS // 2:
        raise EyeToolError("--guard-taps must be between 0 and 15")
    if args.settle_ms < 0:
        raise EyeToolError("--settle-ms cannot be negative")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
        if args.list_ports:
            ports = list_serial_ports()
            if ports:
                for port, description in ports:
                    print(f"{port:8s} {description}")
            else:
                print("No serial ports found.")
            return 0

        args.port = choose_port(args.port)
        if not args.yes:
            if not sys.stdin.isatty():
                raise EyeToolError("use --yes after stopping the pulser and imaging host")
            print("This enables AFE digital test patterns while it calibrates.")
            answer = input("Is the pulser stopped and the imaging host closed? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Cancelled.")
                return 1

        backend = open_serial(args.port, args.baud)
        monitor = AfeMonitor(backend)
        # Let Windows/USB settle after opening, then discard any old console text.
        time.sleep(0.1)
        backend.reset_input_buffer()
        monitor.rx.clear()
        report: Optional[CalibrationReport] = None
        try:
            report = calibrate(monitor, args)
        finally:
            # Never leave deskew/sync/ramp data feeding the imaging pipeline.
            try:
                monitor.pattern_off()
            except Exception as cleanup_error:
                print(f"WARNING: could not disable AFE test patterns: {cleanup_error}",
                      file=sys.stderr)
            monitor.close()

        save_report(report, args.report)
        print()
        print("PASS - AFE eye alignment complete")
        print(f"  DATA tap {report.data_tap:02d}, FCLK tap {report.fclk_tap:02d}, "
              f"BITSLIPs {report.bitslips}")
        print(f"  Report: {args.report.resolve()}")
        print("  These taps are volatile; run the tool again after an FPGA reset.")
        return 0
    except (EyeToolError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
