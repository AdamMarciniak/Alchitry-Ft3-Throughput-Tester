#!/usr/bin/env python3
"""Single-element acquisition and noise analysis for the USB3 ultrasound tester.

This module is deliberately UI-independent.  ``noise_analyzer.py`` supplies the
desktop app and CLI, while the classes here own the proven FT601/SRC_SEQ wire
protocol, signal analysis, and evidence-bundle export.

No FPGA change is required.  Single-element mode is already implemented by
``PulserCtl.set_single_elem``: list slot zero is set to the requested aperture
position and the transmit sequencer repeatedly fires a one-entry list.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import struct
import time
from typing import Callable, Iterable, Optional

import numpy as np

from pulser_ctrl import NS_PER_CYCLE, TRIM_BIAS, PulserCtl, trim_load_file


# Existing host/RTL contract ---------------------------------------------------
FS_HZ = 40_000_000
CLK_HZ = 100_000_000
ADC_BITS = 12
ADC_FULL_SCALE_COUNTS = 1 << (ADC_BITS - 1)  # centred peak: 2048 counts
ADC_CODE_COUNT = 1 << ADC_BITS

XFER = 1024 * 1024
NBUF = 4
PIPE_IN, PIPE_OUT = 0x82, 0x02
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10

LOCK_WORD = 0xA5A55A5A
OP_START, OP_STOP, OP_RST_CNT = 0x01, 0x02, 0x03
OP_SET_SRC = 0x07
OP_SEQ_LEN, OP_SEQ_DLY, OP_SEQ_TGC = 0x0B, 0x0C, 0x0D
OP_SEQ_GAP, OP_SEQ_TGC0 = 0x0E, 0x0F
SRC_SEQ = 2

N_ELEM = 48
ELEM_BITS = 6
ELEM_MASK = (1 << ELEM_BITS) - 1
HDR_SHIFT = 16 + ELEM_BITS
HDR_MAGIC = 0xE1 << (24 - HDR_SHIFT)

FT_STATUS_NAMES = {
    0: "FT_OK", 1: "FT_INVALID_HANDLE", 2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED", 4: "FT_IO_ERROR",
    5: "FT_INSUFFICIENT_RESOURCES", 6: "FT_INVALID_PARAMETER",
    16: "FT_INVALID_ARGS", 17: "FT_NOT_SUPPORTED", 18: "FT_NO_MORE_ITEMS",
    19: "FT_TIMEOUT", 20: "FT_OPERATION_ABORTED", 21: "FT_RESERVED_PIPE",
    22: "FT_INVALID_CONTROL_REQUEST",
}


class CaptureError(RuntimeError):
    """Expected hardware, transport, or acquisition failure."""


class CaptureCancelled(CaptureError):
    """The user cancelled an acquisition."""


def ft_status(status: int) -> str:
    return FT_STATUS_NAMES.get(int(status), f"0x{int(status):X}")


def cmd(op: int, payload: int = 0) -> int:
    return ((op & 0xFF) << 24) | (payload & 0xFFFFFF)


def us_to_cycles(us: float) -> int:
    return max(1, min(0xFFFFFF, int(round(float(us) * CLK_HZ / 1e6))))


def depth_to_words(depth_cm: float, sound_speed_m_s: float) -> int:
    """ADC words for a round-trip capture spanning ``depth_cm``."""
    seconds = 2.0 * float(depth_cm) / 100.0 / float(sound_speed_m_s)
    return max(320, min(0xFFFF, int(seconds * FS_HZ) // 2))


@dataclass
class CaptureSettings:
    """All settings needed to make a repeatable single-element capture."""

    element: int = 0
    frames: int = 128
    depth_cm: float = 14.0
    analysis_start_depth_cm: float = 3.0
    sound_speed_m_s: float = 1496.0
    delay_us: float = 5.0
    damp_us: float = 50.0
    tgc_start: int = 834
    tgc_end: int = 834
    signed_adc: bool = False

    # Explicit transmit values make a report reproducible and avoid inheriting
    # unknown state left by another host app.
    pulse_pairs: int = 2
    pulse_width_ns: float = 100.0
    pulse_dead_ns: float = 40.0
    switch_settle_us: float = 5.0
    mux_inhibit_us: float = 4.5
    ringdown_us: float = 3.0

    def validated(self) -> "CaptureSettings":
        values = asdict(self)
        values["element"] = max(0, min(N_ELEM - 1, int(self.element)))
        values["frames"] = max(8, min(4096, int(self.frames)))
        values["depth_cm"] = max(0.5, min(100.0, float(self.depth_cm)))
        values["analysis_start_depth_cm"] = max(
            0.0, min(values["depth_cm"], float(self.analysis_start_depth_cm))
        )
        values["sound_speed_m_s"] = max(500.0, min(10000.0, float(self.sound_speed_m_s)))
        values["delay_us"] = max(0.0, min(10000.0, float(self.delay_us)))
        values["damp_us"] = max(0.0, min(10000.0, float(self.damp_us)))
        values["tgc_start"] = max(0, min(4095, int(self.tgc_start)))
        values["tgc_end"] = max(values["tgc_start"], min(4095, int(self.tgc_end)))
        values["pulse_pairs"] = max(1, min(255, int(self.pulse_pairs)))
        values["pulse_width_ns"] = max(10.0, min(10000.0, float(self.pulse_width_ns)))
        values["pulse_dead_ns"] = max(40.0, min(10000.0, float(self.pulse_dead_ns)))
        values["switch_settle_us"] = max(4.0, min(10000.0, float(self.switch_settle_us)))
        values["mux_inhibit_us"] = max(4.5, min(10000.0, float(self.mux_inhibit_us)))
        values["ringdown_us"] = max(0.0, min(10000.0, float(self.ringdown_us)))
        return CaptureSettings(**values)

    @property
    def window_words(self) -> int:
        return depth_to_words(self.depth_cm, self.sound_speed_m_s)

    @property
    def samples_per_frame(self) -> int:
        return 2 * self.window_words

    @property
    def window_us(self) -> float:
        return self.samples_per_frame / FS_HZ * 1e6


@dataclass
class CaptureData:
    frames: np.ndarray
    settings: dict
    transport: dict

    def __post_init__(self) -> None:
        a = np.asarray(self.frames)
        if a.ndim != 2:
            raise ValueError("frames must have shape (frame, sample)")
        self.frames = np.ascontiguousarray(a, dtype=np.int16)


class FrameParser:
    """Incremental parser for SRC_SEQ frames, including sample-tag checks."""

    def __init__(self, window_words: int, expected_element: int, signed_adc: bool):
        self.window_words = int(window_words)
        self.frame_words = self.window_words + 1
        self.expected_element = int(expected_element)
        self.signed_adc = bool(signed_adc)
        self.carry = np.empty(0, dtype=np.uint32)
        self.last_frame_counter: Optional[int] = None
        self.stats = {
            "headers_seen": 0,
            "accepted_frames": 0,
            "wrong_element_frames": 0,
            "tag_damaged_frames": 0,
            "sample_tag_discontinuities": 0,
            "frame_counter_discontinuities": 0,
            "estimated_missing_frames": 0,
            "resync_events": 0,
            "discarded_words_during_resync": 0,
        }

    @staticmethod
    def _is_header(words: np.ndarray) -> np.ndarray:
        return (words >> HDR_SHIFT) == HDR_MAGIC

    def _decode(self, packed: np.ndarray) -> list[np.ndarray]:
        if packed.size == 0:
            return []
        rows = packed.reshape(-1, self.frame_words)
        headers = rows[:, 0]
        elems = ((headers >> 16) & ELEM_MASK).astype(np.int32)
        counters = (headers & 0xFFFF).astype(np.int64)
        self.stats["headers_seen"] += int(rows.shape[0])

        if self.last_frame_counter is not None:
            step = (int(counters[0]) - self.last_frame_counter) & 0xFFFF
            if step != 1:
                self.stats["frame_counter_discontinuities"] += 1
                self.stats["estimated_missing_frames"] += max(0, step - 1)
        if counters.size > 1:
            steps = np.diff(counters) & 0xFFFF
            bad = steps != 1
            self.stats["frame_counter_discontinuities"] += int(np.count_nonzero(bad))
            self.stats["estimated_missing_frames"] += int(np.maximum(steps[bad] - 1, 0).sum())
        self.last_frame_counter = int(counters[-1])

        raw16 = np.ascontiguousarray(rows[:, 1:]).view(np.uint16)
        raw16 = raw16.reshape(rows.shape[0], 2 * self.window_words)
        tags = (raw16 >> 12).astype(np.int16)
        diffs = np.diff(tags, axis=1)
        bad_tag = (diffs != 1) & (diffs != -15)
        damaged = np.any(bad_tag, axis=1)
        self.stats["sample_tag_discontinuities"] += int(np.count_nonzero(bad_tag))
        self.stats["tag_damaged_frames"] += int(np.count_nonzero(damaged))

        wrong = elems != self.expected_element
        self.stats["wrong_element_frames"] += int(np.count_nonzero(wrong))
        keep = ~(damaged | wrong)
        if not np.any(keep):
            return []

        codes = (raw16[keep] & 0x0FFF).astype(np.int32)
        if self.signed_adc:
            centred = np.where(codes >= 2048, codes - 4096, codes)
        else:
            centred = codes - 2048
        self.stats["accepted_frames"] += int(centred.shape[0])
        return [np.ascontiguousarray(row, dtype=np.int16) for row in centred]

    def feed(self, words: np.ndarray) -> list[np.ndarray]:
        incoming = np.asarray(words, dtype=np.uint32).reshape(-1)
        w = np.concatenate((self.carry, incoming)) if self.carry.size else incoming
        out: list[np.ndarray] = []
        pos, size = 0, int(w.size)
        while size - pos >= self.frame_words:
            if not bool(self._is_header(w[pos:pos + 1])[0]):
                hits = np.nonzero(self._is_header(w[pos + 1:]))[0]
                self.stats["resync_events"] += 1
                if hits.size == 0:
                    # Retain at most a partial frame.  A header could be in the
                    # retained tail even when the current chunk has no full frame.
                    keep = min(self.frame_words - 1, size - pos)
                    drop = (size - pos) - keep
                    self.stats["discarded_words_during_resync"] += max(0, drop)
                    pos = size - keep
                    break
                skip = 1 + int(hits[0])
                self.stats["discarded_words_during_resync"] += skip
                pos += skip
                continue

            nframes = (size - pos) // self.frame_words
            starts = w[pos:pos + nframes * self.frame_words:self.frame_words]
            valid = self._is_header(starts)
            run = int(np.argmax(~valid)) if not bool(valid.all()) else nframes
            if run:
                stop = pos + run * self.frame_words
                out.extend(self._decode(w[pos:stop]))
                pos = stop
            else:
                # The current word is a header but the next aligned frame is
                # not.  Decode this one, then let the next loop resynchronise.
                stop = pos + self.frame_words
                out.extend(self._decode(w[pos:stop]))
                pos = stop

        self.carry = w[pos:].copy()
        return out


class OVERLAPPED(C.Structure):
    _fields_ = [
        ("Internal", C.c_void_p),
        ("InternalHigh", C.c_void_p),
        ("Pointer", C.c_void_p),
        ("hEvent", C.c_void_p),
    ]


class SingleElementCapture:
    """Bounded FT601 acquisition which always leaves the pulser stopped."""

    def __init__(self, dll_path: Optional[Path] = None):
        self.dll_path = Path(dll_path) if dll_path else Path(__file__).with_name("FTD3XX.dll")

    def capture(
        self,
        requested: CaptureSettings,
        progress: Optional[Callable[[int, int], None]] = None,
        cancel_event=None,
    ) -> CaptureData:
        settings = requested.validated()
        if os.name != "nt":
            raise CaptureError("FTD3XX capture is supported on Windows only")
        if not self.dll_path.exists():
            raise CaptureError(f"FTD3XX.dll not found at {self.dll_path}")

        try:
            d3 = C.WinDLL(str(self.dll_path))
        except OSError as exc:
            raise CaptureError(
                f"Could not load {self.dll_path.name}: {exc}. Check that the DLL and Python are both 64-bit."
            ) from exc
        d3.FT_Create.restype = C.c_ulong
        d3.FT_WritePipe.restype = C.c_ulong

        handle = C.c_void_p()
        status = d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX), C.byref(handle))
        if status != FT_OK:
            raise CaptureError(
                f"FT_Create failed ({ft_status(status)}). Is the Ft+ connected, and are other host apps closed?"
            )

        bufs = [(C.c_ubyte * XFER)() for _ in range(NBUF)]
        views = [np.frombuffer(buf, dtype=np.uint32) for buf in bufs]
        ovs = [OVERLAPPED() for _ in range(NBUF)]
        got = [C.c_ulong(0) for _ in range(NBUF)]
        initialized = [False] * NBUF
        parser = FrameParser(settings.window_words, settings.element, settings.signed_adc)
        captured: list[np.ndarray] = []
        started = False
        pulser: Optional[PulserCtl] = None
        start_time = time.perf_counter()

        def send(word: int, name: str = "") -> None:
            raw = (C.c_ubyte * 4).from_buffer_copy(struct.pack("<I", word & 0xFFFFFFFF))
            sent = C.c_ulong(0)
            st = d3.FT_WritePipe(
                handle, C.c_ubyte(PIPE_OUT), raw, C.c_ulong(4), C.byref(sent), None
            )
            if st != FT_OK or sent.value != 4:
                raise CaptureError(
                    f"control write failed ({name}): {ft_status(st)}, sent {sent.value}/4 bytes"
                )

        def queue_read(i: int) -> None:
            d3.FT_ReadPipeEx(
                handle, C.c_ubyte(PIPE_IN), bufs[i], C.c_ulong(XFER),
                C.byref(got[i]), C.byref(ovs[i]),
            )

        try:
            d3.FT_SetPipeTimeout(handle, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))
            send(LOCK_WORD, "lock")
            time.sleep(0.05)
            send(cmd(OP_RST_CNT), "rst_cnt")
            send(cmd(OP_SET_SRC, SRC_SEQ), "set_src")

            words = settings.window_words
            tgc_inc = max(0, ((settings.tgc_end - settings.tgc_start) * 4096) // words)
            send(cmd(OP_SEQ_LEN, words), "seq_len")
            send(cmd(OP_SEQ_DLY, us_to_cycles(settings.delay_us)), "seq_dly")
            send(cmd(OP_SEQ_GAP, us_to_cycles(settings.damp_us)), "seq_gap")
            send(cmd(OP_SEQ_TGC0, settings.tgc_start), "seq_tgc0")
            send(cmd(OP_SEQ_TGC, tgc_inc), "seq_tgc")

            d3.FT_SetStreamPipe(
                handle, C.c_int(0), C.c_int(0), C.c_ubyte(PIPE_IN), C.c_ulong(XFER)
            )
            d3.FT_SetPipeTimeout(handle, C.c_ubyte(PIPE_IN), C.c_ulong(2000))
            for i in range(NBUF):
                st = d3.FT_InitializeOverlapped(handle, C.byref(ovs[i]))
                if st != FT_OK:
                    raise CaptureError(f"FT_InitializeOverlapped failed: {ft_status(st)}")
                initialized[i] = True
                queue_read(i)

            pulser = PulserCtl(send, cmd)
            pulser.n_cycles = settings.pulse_pairs
            pulser.t_drive_ns = settings.pulse_width_ns
            pulser.t_dead_ns = settings.pulse_dead_ns
            pulser.t_settle_us = settings.switch_settle_us
            pulser.t_inhibit_us = settings.mux_inhibit_us
            pulser.t_ring_us = settings.ringdown_us
            # Cover receive delay + capture + post-window damping, with the
            # same 10 us pacing margin used by tfm_gl_host.py.
            pulser.t_rx_us = settings.delay_us + settings.window_us + settings.damp_us + 10.0
            pulser.single_elem = settings.element
            pulser.chirp_on = False
            pulser.arm = True
            pulser.push_all()  # arm is deliberately the last command
            send(cmd(OP_START), "start")
            started = True

            estimated_period_s = pulser.element_period_us() * 1e-6
            deadline = time.perf_counter() + max(12.0, settings.frames * estimated_period_s * 4.0 + 5.0)
            nread = C.c_ulong(0)
            while len(captured) < settings.frames:
                for i in range(NBUF):
                    if cancel_event is not None and cancel_event.is_set():
                        raise CaptureCancelled("capture cancelled")
                    if time.perf_counter() > deadline:
                        raise CaptureError(
                            f"Timed out after receiving {len(captured)}/{settings.frames} clean frames. "
                            "Check that the pulser is running and no fault is latched."
                        )
                    st = d3.FT_GetOverlappedResult(
                        handle, C.byref(ovs[i]), C.byref(nread), C.c_int(1)
                    )
                    if st != FT_OK:
                        raise CaptureError(f"FT601 read failed: {ft_status(st)}")
                    count = int(nread.value) // 4
                    if count:
                        captured.extend(parser.feed(views[i][:count]))
                        if progress:
                            progress(min(len(captured), settings.frames), settings.frames)
                    queue_read(i)
                    if len(captured) >= settings.frames:
                        break

            elapsed = time.perf_counter() - start_time
            frames = np.stack(captured[:settings.frames])
            meta = asdict(settings)
            meta.update({
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": "ft601_src_seq_single_element",
                "sample_rate_hz": FS_HZ,
                "adc_bits": ADC_BITS,
                "sample_coding": "twos_complement" if settings.signed_adc else "offset_binary",
                "window_words": settings.window_words,
                "samples_per_frame": settings.samples_per_frame,
                "window_us": settings.window_us,
                "estimated_frame_rate_hz": 1.0 / estimated_period_s,
                "pulser_rx_us": pulser.t_rx_us,
                "selected_transmit_trim_ns": float(pulser.trim_ns[settings.element]),
                "transmit_trim_bias_ns": float(TRIM_BIAS * NS_PER_CYCLE),
                "pulser_summary": pulser.summary(),
                "trim_status": pulser.trim_note,
            })
            transport = dict(parser.stats)
            transport.update({
                "requested_frames": settings.frames,
                "capture_seconds": elapsed,
                "clean_frame_rate_hz": settings.frames / max(elapsed, 1e-9),
                "partial_words_at_stop": int(parser.carry.size),
            })
            return CaptureData(frames=frames, settings=meta, transport=transport)
        finally:
            if started:
                try:
                    send(cmd(OP_STOP), "stop")
                except Exception:
                    pass
            if pulser is not None:
                try:
                    pulser.set_arm(False)
                except Exception:
                    pass
            for i, ok in enumerate(initialized):
                if ok:
                    try:
                        d3.FT_ReleaseOverlapped(handle, C.byref(ovs[i]))
                    except Exception:
                        pass
            d3.FT_Close(handle)


# Analysis --------------------------------------------------------------------

@dataclass
class AnalysisResult:
    report: dict
    mean_waveform: np.ndarray
    random_std_waveform: np.ndarray
    total_rms_waveform: np.ndarray
    frequencies_hz: np.ndarray
    random_psd: np.ndarray
    coherent_psd: np.ndarray
    time_blocks: list[dict]
    sample_offset: int = 0


def _rms(a: np.ndarray, axis=None) -> np.ndarray | float:
    return np.sqrt(np.mean(np.square(a, dtype=np.float64), axis=axis))


def _db(value: float, reference: float = ADC_FULL_SCALE_COUNTS) -> float:
    return 20.0 * math.log10(max(float(value), 1e-15) / float(reference))


def _finite(value: float, digits: int = 6) -> float:
    value = float(value)
    return round(value, digits) if math.isfinite(value) else 0.0


def _next_pow2_floor(n: int) -> int:
    return 1 << max(0, int(n).bit_length() - 1)


def welch_psd(rows: np.ndarray, fs_hz: float, nperseg: Optional[int] = None) -> tuple[np.ndarray, np.ndarray]:
    """One-sided Welch PSD averaged over every row, using NumPy only."""
    x = np.asarray(rows, dtype=np.float64)
    if x.ndim == 1:
        x = x[None, :]
    if x.shape[1] < 8:
        raise ValueError("at least eight samples are required for a spectrum")
    if nperseg is None:
        nperseg = min(4096, _next_pow2_floor(x.shape[1]))
    nperseg = max(8, min(int(nperseg), x.shape[1]))
    step = max(1, nperseg // 2)
    starts = list(range(0, x.shape[1] - nperseg + 1, step)) or [0]
    window = np.hanning(nperseg)
    scale = float(fs_hz) * float(np.sum(window * window))
    acc = np.zeros(nperseg // 2 + 1, dtype=np.float64)
    count = 0
    for start in starts:
        seg = x[:, start:start + nperseg]
        seg = seg - np.mean(seg, axis=1, keepdims=True)
        spec = np.fft.rfft(seg * window, axis=1)
        acc += np.sum(np.abs(spec) ** 2, axis=0) / scale
        count += x.shape[0]
    acc /= max(1, count)
    if nperseg % 2 == 0:
        acc[1:-1] *= 2.0
    else:
        acc[1:] *= 2.0
    return np.fft.rfftfreq(nperseg, 1.0 / float(fs_hz)), acc


def _spectrum_peaks(freq: np.ndarray, psd: np.ndarray, limit: int = 12) -> list[dict]:
    if psd.size < 5:
        return []
    floor_eps = np.finfo(np.float64).tiny
    candidates = np.nonzero((psd[1:-1] > psd[:-2]) & (psd[1:-1] >= psd[2:]))[0] + 1
    scored = []
    df = float(freq[1] - freq[0]) if freq.size > 1 else 0.0
    for i in candidates:
        lo, hi = max(1, i - 12), min(psd.size, i + 13)
        neighbourhood = np.concatenate((psd[lo:max(lo, i - 2)], psd[min(hi, i + 3):hi]))
        if neighbourhood.size < 3:
            continue
        local_floor = float(np.median(neighbourhood))
        prominence = 10.0 * math.log10(max(float(psd[i]), floor_eps) / max(local_floor, floor_eps))
        if prominence < 6.0:
            continue
        tone_rms = math.sqrt(max(0.0, float(np.sum(psd[max(0, i - 1):i + 2])) * df))
        scored.append((prominence, {
            "frequency_hz": _finite(freq[i], 2),
            "frequency_mhz": _finite(freq[i] / 1e6, 6),
            "prominence_db": _finite(prominence, 2),
            "estimated_rms_counts": _finite(tone_rms, 4),
            "estimated_rms_dbfs": _finite(_db(tone_rms), 2),
        }))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict] = []
    for _, item in scored:
        if any(abs(item["frequency_hz"] - old["frequency_hz"]) < 3.0 * df for old in selected):
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _band_powers(freq: np.ndarray, psd: np.ndarray) -> list[dict]:
    bands = [
        ("sub_100_khz", 0.0, 100e3),
        ("100_khz_to_1_mhz", 100e3, 1e6),
        ("1_to_2_mhz", 1e6, 2e6),
        ("probe_band_2_to_6_mhz", 2e6, 6e6),
        ("6_to_10_mhz", 6e6, 10e6),
        ("10_to_20_mhz", 10e6, 20e6),
    ]
    df = float(freq[1] - freq[0]) if freq.size > 1 else 0.0
    total = max(float(np.sum(psd) * df), np.finfo(float).tiny)
    out = []
    for name, low, high in bands:
        mask = (freq >= low) & (freq < high if high < FS_HZ / 2 else freq <= high)
        power = float(np.sum(psd[mask]) * df)
        out.append({
            "name": name,
            "low_hz": low,
            "high_hz": high,
            "rms_counts": _finite(math.sqrt(max(0.0, power)), 4),
            "rms_dbfs": _finite(_db(math.sqrt(max(0.0, power))), 2),
            "percent_of_random_noise_power": _finite(100.0 * power / total, 2),
        })
    return out


def _kurtosis(values: np.ndarray) -> float:
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    x = x - np.mean(x)
    var = float(np.mean(x * x))
    if var <= 1e-24:
        return 0.0
    return float(np.mean(x ** 4) / (var * var))


def _classify_region(blocks: list[dict]) -> str:
    random_db = max(b["random_rms_dbfs"] for b in blocks)
    coherent_db = max(b["coherent_rms_dbfs"] for b in blocks)
    kurt = max(b["random_kurtosis"] for b in blocks)
    if kurt >= 10.0:
        return "impulsive_or_bursty"
    if coherent_db >= random_db + 3.0:
        return "repeatable_coherent_artifact"
    return "elevated_random_noise"


def _time_analysis(
    ac: np.ndarray,
    mean_wave: np.ndarray,
    residual: np.ndarray,
    settings: dict,
    block_samples: int = 256,
    sample_offset: int = 0,
) -> tuple[list[dict], list[dict], list[dict]]:
    n = ac.shape[1]
    fs = float(settings.get("sample_rate_hz", FS_HZ))
    c = float(settings.get("sound_speed_m_s", 1496.0))
    delay_s = float(settings.get("delay_us", 0.0)) * 1e-6
    hv_delay_s = (
        float(settings.get("transmit_trim_bias_ns", 0.0))
        + float(settings.get("selected_transmit_trim_ns", 0.0))
    ) * 1e-9
    blocks = []
    for a in range(0, n, block_samples):
        b = min(n, a + block_samples)
        rand = residual[:, a:b]
        coherent = mean_wave[a:b]
        total = ac[:, a:b]
        aa, bb = a + sample_offset, b + sample_offset
        t0, t1 = aa / fs, bb / fs
        blocks.append({
            "index": len(blocks),
            "start_sample": aa,
            "end_sample": bb,
            "start_us": _finite(t0 * 1e6, 3),
            "end_us": _finite(t1 * 1e6, 3),
            "start_depth_cm": _finite(c * (delay_s + t0 - hv_delay_s) * 50.0, 3),
            "end_depth_cm": _finite(c * (delay_s + t1 - hv_delay_s) * 50.0, 3),
            "total_rms_dbfs": _finite(_db(_rms(total)), 2),
            "random_rms_dbfs": _finite(_db(_rms(rand)), 2),
            "coherent_rms_dbfs": _finite(_db(_rms(coherent)), 2),
            "peak_dbfs": _finite(_db(float(np.max(np.abs(total)))), 2),
            "random_kurtosis": _finite(_kurtosis(rand), 3),
        })
    random_levels = np.array([x["random_rms_dbfs"] for x in blocks])
    total_levels = np.array([x["total_rms_dbfs"] for x in blocks])
    random_base = float(np.median(random_levels))
    total_base = float(np.median(total_levels))
    for block in blocks:
        block["random_excess_over_median_db"] = _finite(block["random_rms_dbfs"] - random_base, 2)
        block["total_excess_over_median_db"] = _finite(block["total_rms_dbfs"] - total_base, 2)

    flagged = np.array([
        (b["random_excess_over_median_db"] >= 3.0)
        or (b["total_excess_over_median_db"] >= 6.0)
        or (b["random_kurtosis"] >= 10.0)
        for b in blocks
    ])
    regions = []
    i = 0
    while i < len(blocks):
        if not flagged[i]:
            i += 1
            continue
        j = i + 1
        while j < len(blocks) and flagged[j]:
            j += 1
        group = blocks[i:j]
        regions.append({
            "start_us": group[0]["start_us"],
            "end_us": group[-1]["end_us"],
            "start_depth_cm": group[0]["start_depth_cm"],
            "end_depth_cm": group[-1]["end_depth_cm"],
            "classification": _classify_region(group),
            "max_random_excess_db": max(b["random_excess_over_median_db"] for b in group),
            "max_total_excess_db": max(b["total_excess_over_median_db"] for b in group),
            "max_peak_dbfs": max(b["peak_dbfs"] for b in group),
            "max_kurtosis": max(b["random_kurtosis"] for b in group),
        })
        i = j
    regions.sort(
        key=lambda r: max(r["max_random_excess_db"], r["max_total_excess_db"]),
        reverse=True,
    )
    highest = sorted(
        blocks,
        key=lambda b: max(b["random_rms_dbfs"], b["total_rms_dbfs"]),
        reverse=True,
    )[:8]
    return blocks, regions[:12], highest


def _frame_modulation(frame_values: np.ndarray, frame_rate_hz: float) -> dict:
    values = np.asarray(frame_values, dtype=np.float64)
    if values.size < 16 or frame_rate_hz <= 0:
        return {"available": False, "reason": "need at least 16 frames and a known frame rate"}
    n = _next_pow2_floor(values.size)
    values = values[-n:] - np.mean(values[-n:])
    win = np.hanning(n)
    spec = np.fft.rfft(values * win)
    power = np.abs(spec) ** 2 / max(float(np.sum(win * win)), 1e-15)
    freq = np.fft.rfftfreq(n, 1.0 / frame_rate_hz)
    peaks = _spectrum_peaks(freq, power / max(frame_rate_hz, 1e-9), limit=8)
    return {
        "available": True,
        "frame_rate_hz": _finite(frame_rate_hz, 3),
        "frequency_resolution_hz": _finite(frame_rate_hz / n, 3),
        "peaks": peaks,
        "note": "This spectrum uses one scalar per repeated shot and can expose mains/supply modulation below the shot-rate Nyquist limit.",
    }


def analyze_capture(data: CaptureData) -> AnalysisResult:
    full_frames = np.asarray(data.frames, dtype=np.float64)
    if full_frames.shape[0] < 2 or full_frames.shape[1] < 8:
        raise ValueError("analysis needs at least two frames with eight samples each")

    # Grade only the useful imaging region.  The receive input is connected to
    # the transmit line through a limiter, so overload during/after firing is
    # expected and must not dominate an assessment intended for deeper echoes.
    # tx_sync precedes the physical HV edge by TRIM_BIAS + per-element trim;
    # account for that delay when converting a physical depth to a sample gate.
    fs = float(data.settings.get("sample_rate_hz", FS_HZ))
    c = float(data.settings.get("sound_speed_m_s", 1496.0))
    delay_s = float(data.settings.get("delay_us", 0.0)) * 1e-6
    hv_delay_s = (
        float(data.settings.get("transmit_trim_bias_ns", 0.0))
        + float(data.settings.get("selected_transmit_trim_ns", 0.0))
    ) * 1e-9
    start_depth_cm = float(data.settings.get("analysis_start_depth_cm", 3.0))
    gate_time_s = 2.0 * (start_depth_cm / 100.0) / c - delay_s + hv_delay_s
    gate_sample = max(0, min(full_frames.shape[1] - 8, int(math.ceil(gate_time_s * fs))))
    frames = full_frames[:, gate_sample:]

    full_dc = np.mean(full_frames, axis=1)
    full_ac = full_frames - full_dc[:, None]
    full_mean = np.mean(full_ac, axis=0)
    full_residual = full_ac - full_mean[None, :]
    full_clip = (full_frames <= -2048) | (full_frames >= 2047)
    full_near_rail = (full_frames <= -2040) | (full_frames >= 2039)

    excluded = full_frames[:, :gate_sample]
    if excluded.shape[1]:
        excluded_dc = np.mean(excluded, axis=1)
        excluded_ac = excluded - excluded_dc[:, None]
        excluded_mean = np.mean(excluded_ac, axis=0)
        excluded_residual = excluded_ac - excluded_mean[None, :]
        excluded_summary = {
            "available": True,
            "samples": int(excluded.shape[1]),
            "end_capture_time_us": _finite(gate_sample / fs * 1e6, 3),
            "peak_counts": _finite(np.max(np.abs(excluded)), 2),
            "peak_dbfs": _finite(_db(np.max(np.abs(excluded))), 2),
            "random_rms_counts": _finite(_rms(excluded_residual), 4),
            "random_rms_dbfs": _finite(_db(_rms(excluded_residual)), 2),
            "coherent_rms_counts": _finite(_rms(excluded_mean), 4),
            "coherent_rms_dbfs": _finite(_db(_rms(excluded_mean)), 2),
            "clipped_samples_percent": _finite(100.0 * np.mean((excluded <= -2048) | (excluded >= 2047)), 8),
            "residual_kurtosis": _finite(_kurtosis(excluded_residual), 3),
            "assessment_role": "context_only_expected_limiter_and_ringdown_not_used_for_overall_status",
        }
    else:
        excluded_summary = {"available": False, "samples": 0}

    # Remove each frame's DC separately before coherent/random decomposition.
    # DC itself is reported below; allowing it into mean_wave would make a
    # static ADC offset look like deterministic acoustic feedthrough.
    frame_dc = np.mean(frames, axis=1)
    ac = frames - frame_dc[:, None]
    mean_wave = np.mean(ac, axis=0)
    residual = ac - mean_wave[None, :]
    random_std_wave = np.std(residual, axis=0, ddof=1)
    total_rms_wave = np.sqrt(np.mean(np.square(ac), axis=0))

    total_rms = float(_rms(ac))
    coherent_rms = float(_rms(mean_wave))
    random_rms = float(_rms(residual))
    peak = float(np.max(np.abs(frames)))
    p2p = float(np.max(frames) - np.min(frames))
    clip = (frames <= -2048) | (frames >= 2047)
    near_rail = (frames <= -2040) | (frames >= 2039)

    freq, random_psd = welch_psd(residual, fs)
    _, coherent_psd = welch_psd(mean_wave, fs, nperseg=(freq.size - 1) * 2)
    df = float(freq[1] - freq[0])
    positive = random_psd[1:] if random_psd.size > 1 else random_psd
    spectral_flatness = float(
        np.exp(np.mean(np.log(np.maximum(positive, np.finfo(float).tiny))))
        / max(float(np.mean(positive)), np.finfo(float).tiny)
    )
    tones = _spectrum_peaks(freq, random_psd)
    coherent_tones = _spectrum_peaks(freq, coherent_psd)
    bands = _band_powers(freq, random_psd)
    blocks, regions, highest_blocks = _time_analysis(
        ac, mean_wave, residual, data.settings, sample_offset=gate_sample
    )

    frame_rms = np.asarray(_rms(ac, axis=1))
    norms = np.linalg.norm(ac, axis=1) * max(float(np.linalg.norm(mean_wave)), 1e-15)
    correlations = np.sum(ac * mean_wave[None, :], axis=1) / np.maximum(norms, 1e-15)
    frame_rate = float(data.settings.get("estimated_frame_rate_hz", 0.0))
    modulation = {
        "frame_dc": _frame_modulation(frame_dc, frame_rate),
        "frame_rms": _frame_modulation(frame_rms, frame_rate),
    }

    coding = data.settings.get("sample_coding", "offset_binary")
    centred_i = data.frames[:, gate_sample:].astype(np.int32)
    raw_codes = ((centred_i & 0xFFF) if coding == "twos_complement" else (centred_i + 2048)) & 0xFFF
    bit_ones = [float(np.mean((raw_codes >> bit) & 1)) for bit in range(ADC_BITS)]
    stuck = [bit for bit, balance in enumerate(bit_ones) if balance < 1e-6 or balance > 1.0 - 1e-6]
    lsb_toggle = float(np.mean((raw_codes[:, 1:] & 1) != (raw_codes[:, :-1] & 1)))
    unique_codes = int(np.unique(raw_codes).size)
    effective_bits = math.log2(ADC_CODE_COUNT / (math.sqrt(12.0) * max(random_rms, 1e-15)))

    random_fraction = random_rms ** 2 / max(total_rms ** 2, 1e-30)
    time_spread = max(b["random_rms_dbfs"] for b in blocks) - min(b["random_rms_dbfs"] for b in blocks)
    kurt = _kurtosis(residual)

    integrity_bad = sum(int(data.transport.get(key, 0)) for key in (
        "wrong_element_frames", "tag_damaged_frames", "frame_counter_discontinuities",
        "resync_events",
    ))
    findings = []

    def finding(severity: str, code: str, summary: str, evidence: dict, next_test: str) -> None:
        findings.append({
            "severity": severity,
            "code": code,
            "summary": summary,
            "evidence": evidence,
            "next_test": next_test,
        })

    if integrity_bad:
        finding(
            "high", "digital_integrity",
            "The capture contains transport/frame integrity errors; do not interpret all discontinuities as analog noise.",
            {k: int(data.transport.get(k, 0)) for k in (
                "wrong_element_frames", "tag_damaged_frames", "sample_tag_discontinuities",
                "frame_counter_discontinuities", "resync_events")},
            "Repeat with the FPGA counter/eye tools and check FT601 throughput before changing the analog front end.",
        )
    if float(np.mean(clip)) > 0:
        sev = "high" if float(np.mean(clip)) >= 1e-3 else "medium"
        finding(
            sev, "adc_clipping", "Samples reached the ADC rails, so RMS and spectral results are distortion-limited.",
            {"clipped_percent": _finite(100.0 * np.mean(clip), 6), "near_rail_percent": _finite(100.0 * np.mean(near_rail), 6)},
            "Lower fixed TGC and/or transmit level, then repeat until clipped samples are zero.",
        )
    if random_rms > 0 and _db(random_rms) > -50.0:
        sev = "high" if _db(random_rms) > -36.0 else "medium"
        finding(
            sev, "broadband_noise_level", "Measured random noise is high relative to ADC full scale.",
            {"random_rms_counts": _finite(random_rms, 4), "random_rms_dbfs": _finite(_db(random_rms), 2)},
            "Repeat at several fixed TGC values and with the probe/cable substituted to separate input-referred noise from gain-stage or supply noise.",
        )
    if coherent_rms > random_rms and coherent_rms > 2.0:
        finding(
            "medium", "repeatable_artifact",
            "Repeatable energy is stronger than frame-to-frame random noise, consistent with transmit feedthrough, ringdown, or synchronous pickup.",
            {"coherent_rms_dbfs": _finite(_db(coherent_rms), 2), "random_rms_dbfs": _finite(_db(random_rms), 2), "median_frame_correlation": _finite(np.median(correlations), 4)},
            "Compare probe-in-air, probe-loaded, and transmit-voltage conditions; repeatable early energy that tracks voltage/loading is likely acoustic or HV feedthrough.",
        )
    strongest_lines = sorted(
        [dict(tone, component="random_residual") for tone in tones]
        + [dict(tone, component="repeatable_waveform") for tone in coherent_tones],
        key=lambda tone: tone["prominence_db"],
        reverse=True,
    )
    # Prominence alone over-flags the first FFT bin of a tiny exponential
    # limiter-recovery tail: it can stand 30 dB above an even tinier local
    # floor while remaining well below the broadband noise.  A line becomes an
    # assessment finding only when it is both prominent and within 3 dB of the
    # measured random-noise RMS (with -80 dBFS as a conservative floor).
    actionable_lines = [
        line for line in strongest_lines
        if line["prominence_db"] >= 12.0
        and line["estimated_rms_dbfs"] >= max(-80.0, _db(random_rms) - 3.0)
    ]
    if actionable_lines:
        finding(
            "medium", "narrowband_interference",
            "One or more narrow spectral lines rise clearly above the local noise floor; the component label shows whether each line repeats with the shot.",
            {"strongest_tones": actionable_lines[:8]},
            "Correlate the listed frequencies and harmonics with switching regulators, clocks, USB activity, and the transmit centre frequency; vary transmit amplitude to distinguish acoustic/ringdown lines from electrical pickup.",
        )
    if time_spread >= 6.0:
        finding(
            "medium", "time_localized_noise",
            "Noise is not stationary across the receive window; one or more time/depth regions are materially worse.",
            {"random_noise_spread_db": _finite(time_spread, 2), "regions": regions[:5]},
            "Use the reported time/depth gates to relate each rise to ringdown, TGC changes, supply settling, or a fixed-delay digital event.",
        )
    if kurt >= 8.0:
        finding(
            "medium", "impulsive_noise", "The random residual has heavy tails, indicating intermittent spikes or burst noise.",
            {"residual_kurtosis": _finite(kurt, 3), "gaussian_reference": 3.0},
            "Capture more frames and trigger a bench scope on the affected time gate while monitoring rails and digital control lines.",
        )
    if int(data.settings.get("tgc_end", 0)) != int(data.settings.get("tgc_start", 0)):
        finding(
            "info", "tgc_confound", "TGC changed during the window, so raw level-versus-depth includes intentional gain variation.",
            {"tgc_start": data.settings.get("tgc_start"), "tgc_end": data.settings.get("tgc_end")},
            "Repeat with equal TGC start/end for hardware-noise localization, then compare with the imaging TGC ramp.",
        )
    if not findings:
        finding(
            "info", "no_threshold_findings", "No generic clipping, integrity, tonal, impulsive, or high-noise threshold was crossed.",
            {"random_rms_dbfs": _finite(_db(random_rms), 2)},
            "Treat this as a baseline, not a calibrated pass/fail; compare it with captures under the failing condition.",
        )

    severity_rank = {"info": 0, "medium": 1, "high": 2}
    max_severity = max(findings, key=lambda x: severity_rank[x["severity"]])["severity"]
    status = {"info": "baseline_or_clean", "medium": "investigate", "high": "invalid_or_severe"}[max_severity]

    report = {
        "schema": "usb3_tester.single_element_noise.v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": status,
        "threshold_note": "Severity thresholds are generic engineering triage, not a calibrated AFE5804 production limit.",
        "capture_settings": data.settings,
        "transport_integrity": data.transport,
        "analysis_gate": {
            "requested_start_depth_cm": _finite(start_depth_cm, 3),
            "actual_start_depth_cm": _finite(c * (delay_s + gate_sample / fs - hv_delay_s) * 50.0, 3),
            "start_sample": int(gate_sample),
            "start_capture_time_us": _finite(gate_sample / fs * 1e6, 3),
            "physical_hv_delay_after_tx_sync_us": _finite(hv_delay_s * 1e6, 3),
            "selected_transmit_trim_ns": _finite(data.settings.get("selected_transmit_trim_ns", 0.0), 1),
            "transmit_trim_bias_ns": _finite(data.settings.get("transmit_trim_bias_ns", 0.0), 1),
            "note": "Only samples at/after this physical-depth gate affect the assessment. Earlier limiter saturation and ringdown remain in excluded_near_field.",
        },
        "excluded_near_field": excluded_summary,
        "full_capture_context": {
            "samples_per_frame": int(full_frames.shape[1]),
            "duration_per_frame_us": _finite(full_frames.shape[1] / fs * 1e6, 3),
            "peak_counts": _finite(np.max(np.abs(full_frames)), 2),
            "peak_dbfs": _finite(_db(np.max(np.abs(full_frames))), 2),
            "total_ac_rms_counts": _finite(_rms(full_ac), 4),
            "random_residual_rms_counts": _finite(_rms(full_residual), 4),
            "coherent_rms_counts": _finite(_rms(full_mean), 4),
            "clipped_samples_percent": _finite(100.0 * np.mean(full_clip), 8),
            "near_rail_samples_percent": _finite(100.0 * np.mean(full_near_rail), 8),
            "assessment_role": "context_only_not_used_for_overall_status",
        },
        "summary": {
            "frames_analyzed": int(frames.shape[0]),
            "samples_per_frame": int(frames.shape[1]),
            "duration_per_frame_us": _finite(frames.shape[1] / fs * 1e6, 3),
            "analysis_start_depth_cm": _finite(c * (delay_s + gate_sample / fs - hv_delay_s) * 50.0, 3),
            "dc_mean_counts": _finite(np.mean(frame_dc), 4),
            "dc_drift_std_counts": _finite(np.std(frame_dc, ddof=1), 4),
            "total_ac_rms_counts": _finite(total_rms, 4),
            "total_ac_rms_dbfs": _finite(_db(total_rms), 2),
            "random_rms_counts": _finite(random_rms, 4),
            "random_rms_dbfs": _finite(_db(random_rms), 2),
            "coherent_rms_counts": _finite(coherent_rms, 4),
            "coherent_rms_dbfs": _finite(_db(coherent_rms), 2),
            "random_fraction_of_ac_power_percent": _finite(100.0 * random_fraction, 2),
            "peak_counts": _finite(peak, 2),
            "peak_dbfs": _finite(_db(peak), 2),
            "peak_to_peak_counts": _finite(p2p, 2),
            "crest_factor_db": _finite(20.0 * math.log10(max(peak, 1e-15) / max(total_rms, 1e-15)), 2),
            "clipped_samples_percent": _finite(100.0 * np.mean(clip), 8),
            "near_rail_samples_percent": _finite(100.0 * np.mean(near_rail), 8),
            "residual_kurtosis": _finite(kurt, 3),
            "median_frame_correlation_to_mean": _finite(np.median(correlations), 5),
            "frame_rms_variation_percent": _finite(100.0 * np.std(frame_rms, ddof=1) / max(np.mean(frame_rms), 1e-15), 3),
            "effective_bits_from_random_noise": _finite(max(0.0, min(ADC_BITS, effective_bits)), 3),
        },
        "adc_code_health": {
            "sample_coding": coding,
            "unique_codes_observed": unique_codes,
            "observed_code_min": int(np.min(raw_codes)),
            "observed_code_max": int(np.max(raw_codes)),
            "lsb_toggle_percent": _finite(100.0 * lsb_toggle, 3),
            "bit_one_fraction_lsb_to_msb": [_finite(x, 6) for x in bit_ones],
            "fully_static_bits": stuck,
            "note": "Static upper bits can be normal for a very small input range; this is a diagnostic clue, not a DNL test.",
        },
        "spectrum": {
            "method": "one-sided Hann Welch PSD, 50% overlap, DC removed per frame",
            "frequency_resolution_hz": _finite(df, 3),
            "spectral_flatness_0_to_1": _finite(spectral_flatness, 6),
            "random_noise_tones": tones,
            "repeatable_waveform_tones": coherent_tones,
            "random_noise_bands": bands,
            "repeatable_waveform_bands": _band_powers(freq, coherent_psd),
        },
        "time_depth_localization": {
            "block_samples": 256,
            "block_us": _finite(256 / fs * 1e6, 3),
            "depth_mapping": "one-way equivalent depth = sound_speed * (tx_sync_to_capture_delay + sample_time - physical_HV_delay_after_tx_sync) / 2",
            "localized_regions": regions,
            "highest_noise_blocks": highest_blocks,
            "all_blocks": blocks,
        },
        "shot_to_shot_modulation": {
            **modulation,
            "interpretation": "Frame-DC modulation is sensitive to baseline/supply movement; frame-RMS modulation is sensitive to gain or interference amplitude changing between shots.",
        },
        "findings": findings,
        "recommended_comparisons": [
            "Same settings with probe face in air versus acoustically loaded/coupled.",
            "Same fixed TGC at two or three gain codes; input noise should scale predictably while post-gain pickup may not.",
            "Same element with transmit voltage reduced or disabled upstream, if the bench setup provides a safe HV control.",
            "Neighbouring elements with identical settings to separate a shared receive-path issue from one mux/probe path.",
            "Battery/linear bench supplies versus normal switchers, and USB connected through the normal versus isolated ground arrangement.",
        ],
    }
    return AnalysisResult(
        report=report,
        mean_waveform=mean_wave,
        random_std_waveform=random_std_wave,
        total_rms_waveform=total_rms_wave,
        frequencies_hz=freq,
        random_psd=random_psd,
        coherent_psd=coherent_psd,
        time_blocks=blocks,
        sample_offset=gate_sample,
    )


# Evidence bundle -------------------------------------------------------------

def save_capture_npz(data: CaptureData, path: Path) -> Path:
    path = Path(path)
    metadata = json.dumps({"settings": data.settings, "transport": data.transport})
    np.savez_compressed(path, frames=data.frames, metadata_json=np.array(metadata))
    return path


def load_capture_npz(path: Path) -> CaptureData:
    with np.load(Path(path), allow_pickle=False) as saved:
        frames = saved["frames"]
        metadata = json.loads(str(saved["metadata_json"].item()))
    settings = metadata["settings"]
    # v1 bundles predate trim-aware depth mapping.  Use the local calibration
    # as a best-effort migration and label the provenance; new captures embed
    # the selected value and never depend on mutable external state.
    if "selected_transmit_trim_ns" not in settings:
        trim_ns, note = trim_load_file(n_elem=N_ELEM)
        element = max(0, min(N_ELEM - 1, int(settings.get("element", 0))))
        settings["selected_transmit_trim_ns"] = float(trim_ns[element])
        settings["transmit_trim_bias_ns"] = float(TRIM_BIAS * NS_PER_CYCLE)
        settings["trim_metadata_migration"] = f"selected value recovered from local trim file: {note}"
    settings.setdefault("analysis_start_depth_cm", 3.0)
    return CaptureData(frames=frames, settings=settings, transport=metadata["transport"])


def _write_waveform_csv(data: CaptureData, result: AnalysisResult, path: Path) -> None:
    fs = float(data.settings.get("sample_rate_hz", FS_HZ))
    c = float(data.settings.get("sound_speed_m_s", 1496.0))
    delay = float(data.settings.get("delay_us", 0.0)) * 1e-6
    hv_delay = (
        float(data.settings.get("transmit_trim_bias_ns", 0.0))
        + float(data.settings.get("selected_transmit_trim_ns", 0.0))
    ) * 1e-9
    with Path(path).open("w", newline="") as out:
        out.write("sample,time_us,equivalent_depth_cm,mean_counts,random_std_counts,total_rms_counts\n")
        for relative_i, (mean, std, total) in enumerate(zip(
            result.mean_waveform, result.random_std_waveform, result.total_rms_waveform
        )):
            i = relative_i + result.sample_offset
            t = i / fs
            depth = c * (delay + t - hv_delay) * 50.0
            out.write(f"{i},{t * 1e6:.6f},{depth:.6f},{mean:.6f},{std:.6f},{total:.6f}\n")


def _polyline(values: np.ndarray, x0: float, y0: float, width: float, height: float,
              ymin: float, ymax: float, max_points: int = 1500) -> str:
    a = np.asarray(values, dtype=float)
    if a.size > max_points:
        idx = np.linspace(0, a.size - 1, max_points).astype(int)
        a = a[idx]
    else:
        idx = np.arange(a.size)
    den = max(ymax - ymin, 1e-15)
    xs = x0 + width * idx / max(1, values.size - 1)
    ys = y0 + height * (ymax - a) / den
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))


def _svg_overview(data: CaptureData, result: AnalysisResult, path: Path) -> None:
    width, height = 1200, 900
    left, plot_w = 90, 1060
    panel_h = 210
    mean = result.mean_waveform
    std = result.random_std_waveform
    envelope = max(float(np.percentile(np.abs(mean) + std, 99.5)), 1.0)
    blocks = result.time_blocks
    total_db = np.array([b["total_rms_dbfs"] for b in blocks])
    random_db = np.array([b["random_rms_dbfs"] for b in blocks])
    coherent_db = np.array([b["coherent_rms_dbfs"] for b in blocks])
    f = result.frequencies_hz
    p = 10.0 * np.log10(np.maximum(result.random_psd, np.finfo(float).tiny))
    pc = 10.0 * np.log10(np.maximum(result.coherent_psd, np.finfo(float).tiny))
    ptop = max(float(np.percentile(p[1:], 99.8)), float(np.percentile(pc[1:], 99.8))) + 5.0
    pbot = ptop - 90.0
    fs = float(data.settings.get("sample_rate_hz", FS_HZ))
    duration_us = mean.size / fs * 1e6
    time0_us = result.sample_offset / fs * 1e6
    time1_us = time0_us + duration_us
    depth0 = float(result.report["analysis_gate"]["actual_start_depth_cm"])
    depth1 = float(blocks[-1]["end_depth_cm"])

    def text(x, y, value, size=16, fill="#b9cad4", anchor="start"):
        return f'<text x="{x}" y="{y}" fill="{fill}" font-family="Segoe UI,Arial" font-size="{size}" text-anchor="{anchor}">{html.escape(str(value))}</text>'

    def panel(y, title, ylabel):
        return (
            f'<rect x="{left}" y="{y}" width="{plot_w}" height="{panel_h}" fill="#0a0e12" stroke="#33505f"/>'
            + text(left, y - 12, title, 18, "#e3edf2")
            + text(22, y + panel_h / 2, ylabel, 14, "#8299a8")
        )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#101418"/>',
        text(40, 42, f"Single-element noise report — element {data.settings.get('element', '?')}", 26, "#eef7fa"),
        text(40, 70, f"{data.frames.shape[0]} frames · grading {depth0:.2f}–{depth1:.2f} cm · expected near-field limiter interval excluded", 15, "#8299a8"),
    ]
    y1 = 115
    svg.append(panel(y1, "Repeatable waveform with ±1σ random noise", "ADC counts"))
    upper = mean + std
    lower = mean - std
    upper_pts = _polyline(upper, left, y1, plot_w, panel_h, -envelope, envelope)
    lower_pts = _polyline(lower, left, y1, plot_w, panel_h, -envelope, envelope)
    svg.append(f'<polyline points="{upper_pts}" fill="none" stroke="#31576c" stroke-width="1"/>')
    svg.append(f'<polyline points="{lower_pts}" fill="none" stroke="#31576c" stroke-width="1"/>')
    svg.append(f'<polyline points="{_polyline(mean, left, y1, plot_w, panel_h, -envelope, envelope)}" fill="none" stroke="#4dffd2" stroke-width="1.4"/>')
    svg.append(text(left, y1 + panel_h + 22, f"{time0_us:.1f} us", 13, "#8299a8"))
    svg.append(text(left + plot_w, y1 + panel_h + 22, f"{time1_us:.1f} us", 13, "#8299a8", "end"))

    y2 = 405
    svg.append(panel(y2, "Noise location by receive-time block", "dBFS RMS"))
    ymin = min(-120.0, float(np.min([total_db, random_db, coherent_db])) - 3)
    ymax = min(0.0, float(np.max([total_db, random_db, coherent_db])) + 3)
    for values, color, label in (
        (total_db, "#f2cf66", "total"), (random_db, "#ff7a90", "random"),
        (coherent_db, "#4dffd2", "repeatable"),
    ):
        svg.append(f'<polyline points="{_polyline(values, left, y2, plot_w, panel_h, ymin, ymax)}" fill="none" stroke="{color}" stroke-width="2"/>')
        svg.append(text(left + 850 + 75 * (label != "total"), y2 - 12, label, 13, color))
    svg.append(text(left, y2 + panel_h + 22, f"{depth0:.2f} cm", 13, "#8299a8"))
    svg.append(text(left + plot_w, y2 + panel_h + 22, f"{depth1:.2f} cm", 13, "#8299a8", "end"))

    y3 = 695
    ph = 150
    svg.append(f'<rect x="{left}" y="{y3}" width="{plot_w}" height="{ph}" fill="#0a0e12" stroke="#33505f"/>')
    svg.append(text(left, y3 - 12, "Power spectral density", 18, "#e3edf2"))
    svg.append(text(22, y3 + ph / 2, "dB counts²/Hz", 14, "#8299a8"))
    svg.append(f'<polyline points="{_polyline(p, left, y3, plot_w, ph, pbot, ptop)}" fill="none" stroke="#ff7a90" stroke-width="1.5"/>')
    svg.append(f'<polyline points="{_polyline(pc, left, y3, plot_w, ph, pbot, ptop)}" fill="none" stroke="#4dffd2" stroke-width="1.2"/>')
    svg.append(text(left, y3 + ph + 22, "0 MHz", 13, "#8299a8"))
    svg.append(text(left + plot_w, y3 + ph + 22, f"{f[-1] / 1e6:.0f} MHz", 13, "#8299a8", "end"))
    svg.append("</svg>")
    Path(path).write_text("\n".join(svg), encoding="utf-8")


def _markdown_report(report: dict) -> str:
    s = report["summary"]
    gate = report["analysis_gate"]
    excluded = report["excluded_near_field"]
    lines = [
        "# Single-element noise analysis",
        "",
        f"Overall triage: **{report['overall_status']}**",
        "",
        report["threshold_note"],
        "",
        f"Assessment gate starts at **{gate['actual_start_depth_cm']:.3f} cm** "
        f"({gate['start_capture_time_us']:.3f} µs into the captured waveform). "
        "The earlier limiter saturation/ringdown interval is retained as context but is not graded.",
        "",
        "## Core measurements",
        "",
        "| Measurement | Value |",
        "|---|---:|",
        f"| Frames | {s['frames_analyzed']} |",
        f"| Random noise | {s['random_rms_counts']:.3f} counts ({s['random_rms_dbfs']:.2f} dBFS RMS) |",
        f"| Repeatable component | {s['coherent_rms_counts']:.3f} counts ({s['coherent_rms_dbfs']:.2f} dBFS RMS) |",
        f"| Total AC | {s['total_ac_rms_counts']:.3f} counts ({s['total_ac_rms_dbfs']:.2f} dBFS RMS) |",
        f"| Peak | {s['peak_counts']:.1f} counts ({s['peak_dbfs']:.2f} dBFS) |",
        f"| Clipped samples | {s['clipped_samples_percent']:.8f}% |",
        f"| Residual kurtosis | {s['residual_kurtosis']:.3f} (Gaussian = 3) |",
        f"| Effective bits from random noise | {s['effective_bits_from_random_noise']:.3f} |",
        "",
        "## Excluded near-field context",
        "",
    ]
    if excluded.get("available"):
        lines.extend([
            f"The ignored interval peaks at {excluded['peak_counts']:.1f} counts "
            f"({excluded['peak_dbfs']:.2f} dBFS) and has {excluded['coherent_rms_dbfs']:.2f} dBFS "
            "of repeatable energy. These values do not affect the overall assessment.",
            "",
        ])
    lines.extend([
        "## Findings",
        "",
    ])
    for item in report["findings"]:
        lines.extend([
            f"### {item['severity'].upper()}: {item['summary']}",
            "",
            f"Next test: {item['next_test']}",
            "",
        ])
    tones = report["spectrum"]["random_noise_tones"]
    lines.extend(["## Strongest random-noise tones", ""])
    if tones:
        lines.extend(["| Frequency | Prominence | Estimated RMS |", "|---:|---:|---:|"])
        for tone in tones[:8]:
            lines.append(
                f"| {tone['frequency_mhz']:.6f} MHz | {tone['prominence_db']:.2f} dB | {tone['estimated_rms_dbfs']:.2f} dBFS |"
            )
    else:
        lines.append("No narrow line exceeded 6 dB prominence over its local floor.")
    regions = report["time_depth_localization"]["localized_regions"]
    lines.extend(["", "## Localized regions", ""])
    if regions:
        lines.extend(["| Time | Equivalent depth | Classification | Excess |", "|---:|---:|---|---:|"])
        for region in regions[:10]:
            excess = max(region["max_random_excess_db"], region["max_total_excess_db"])
            lines.append(
                f"| {region['start_us']:.3f}–{region['end_us']:.3f} us | "
                f"{region['start_depth_cm']:.3f}–{region['end_depth_cm']:.3f} cm | "
                f"{region['classification']} | {excess:.2f} dB |"
            )
    else:
        lines.append("No receive-time block crossed the localization threshold.")
    lines.extend([
        "",
        "## Important interpretation notes",
        "",
        "- The equivalent depth assumes a round trip at the configured sound speed; electronic pickup is localized correctly in time but not physically at that depth.",
        "- Repeatable energy is not automatically noise: it can include the wanted echo, transmit feedthrough, and probe ringdown.",
        "- Absolute pass/fail limits require a calibrated input termination and known AFE gain. Use matched-condition comparisons.",
        "- Inspect `analysis.json` for complete transport counters, band powers, block data, and machine-readable evidence.",
    ])
    return "\n".join(lines) + "\n"


def _llm_prompt(report: dict) -> str:
    return (
        "Diagnose this single-element ultrasound receive-chain noise capture.\n\n"
        "Use analysis.json as the primary structured evidence and report.md/overview.svg for context. Grade only the "
        "configured analysis_gate. The receiver is directly connected to the transmit line through a limiter, so the "
        "excluded_near_field saturation/ringdown interval is expected context and is not an imaging-region defect. "
        "Separate these failure classes explicitly: (1) FT601/frame/tag corruption, (2) ADC clipping or coding error, "
        "(3) repeatable transmit feedthrough/ringdown, (4) narrowband electrical pickup, (5) broadband random noise, "
        "and (6) time-varying or impulsive noise. Do not call a repeatable echo 'random noise'.\n\n"
        "For each likely cause, cite the exact metric, tone frequency, or time/depth region that supports it; state what "
        "evidence argues against it; rank the causes; and propose the smallest discriminating bench test. Remember that "
        "equivalent depth is derived from time-of-flight, so electrical pickup has a valid time coordinate but not a "
        "literal physical depth. Generic severity thresholds are triage only.\n\n"
        f"Current tool assessment: {report['overall_status']}.\n"
    )


def export_bundle(data: CaptureData, result: AnalysisResult, output_dir: Path) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "capture": save_capture_npz(data, output / "capture.npz"),
        "analysis": output / "analysis.json",
        "report": output / "report.md",
        "waveform": output / "waveform.csv",
        "overview": output / "overview.svg",
        "llm_prompt": output / "llm_prompt.txt",
    }
    paths["analysis"].write_text(json.dumps(result.report, indent=2), encoding="utf-8")
    paths["report"].write_text(_markdown_report(result.report), encoding="utf-8")
    _write_waveform_csv(data, result, paths["waveform"])
    _svg_overview(data, result, paths["overview"])
    paths["llm_prompt"].write_text(_llm_prompt(result.report), encoding="utf-8")
    return paths


def simulate_capture(requested: CaptureSettings, seed: int = 12345) -> CaptureData:
    """Deterministic fault-rich capture for UI, export, and regression testing."""
    settings = requested.validated()
    rng = np.random.default_rng(seed)
    nframes, nsamp = settings.frames, settings.samples_per_frame
    t = np.arange(nsamp, dtype=np.float64) / FS_HZ
    frame_period = settings.delay_us * 1e-6 + settings.window_us * 1e-6 + settings.damp_us * 1e-6 + 25e-6

    # A repeatable early ringdown plus two electrical lines.  The 7.25 MHz line
    # is localized to a later gate so the time/depth detector has real work.
    coherent = 170.0 * np.exp(-t / 9e-6) * np.sin(2 * np.pi * 3.55e6 * t)
    coherent += 8.0 * np.sin(2 * np.pi * 1.25e6 * t + 0.3)
    gate = np.exp(-0.5 * ((t - 78e-6) / 8e-6) ** 2)
    localized = 24.0 * gate * np.sin(2 * np.pi * 7.25e6 * t)
    frames = np.empty((nframes, nsamp), dtype=np.float64)
    for i in range(nframes):
        noise = rng.normal(0.0, 5.0, nsamp)
        noise += rng.normal(0.0, 12.0, nsamp) * gate
        slow = 10.0 * math.sin(2 * math.pi * 60.0 * i * frame_period)
        frames[i] = coherent + localized + noise + slow
    for i in range(0, nframes, 23):
        j = min(nsamp - 3, int(0.62 * nsamp) + i % 17)
        frames[i, j:j + 3] += np.array([250.0, -330.0, 180.0])
    frames = np.clip(np.rint(frames), -2048, 2047).astype(np.int16)
    meta = asdict(settings)
    meta.update({
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "simulation",
        "sample_rate_hz": FS_HZ,
        "adc_bits": ADC_BITS,
        "sample_coding": "twos_complement" if settings.signed_adc else "offset_binary",
        "window_words": settings.window_words,
        "samples_per_frame": settings.samples_per_frame,
        "window_us": settings.window_us,
        "estimated_frame_rate_hz": 1.0 / frame_period,
        "selected_transmit_trim_ns": 0.0,
        "transmit_trim_bias_ns": 0.0,
        "simulation_note": "Fault-rich deterministic demo: ringdown, tones, localized noise, impulses, and 60 Hz frame modulation.",
    })
    transport = {
        "requested_frames": nframes,
        "headers_seen": nframes,
        "accepted_frames": nframes,
        "wrong_element_frames": 0,
        "tag_damaged_frames": 0,
        "sample_tag_discontinuities": 0,
        "frame_counter_discontinuities": 0,
        "estimated_missing_frames": 0,
        "resync_events": 0,
        "discarded_words_during_resync": 0,
        "capture_seconds": nframes * frame_period,
        "clean_frame_rate_hz": 1.0 / frame_period,
        "partial_words_at_stop": 0,
    }
    return CaptureData(frames=frames, settings=meta, transport=transport)
