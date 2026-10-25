"""Portable RF sessions and diagnostics. No GUI, USB, or FPGA side effects.

python host/rf_debug.py recording.rf.npz --report report.json
The archive contains ordinary NPY arrays and JSON; no pickle is ever used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
import uuid
import zipfile
import zlib

import numpy as np

SCHEMA = "usb3-tester-rf"
VERSION = 1
MAX_RF_BYTES = 2300 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024


def json_bytes(value):
    def plain(v):
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, np.generic):
            return v.item()
        raise TypeError(f"Cannot serialize {type(v).__name__}")
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False,
                      default=plain).encode("utf-8")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_bytes(json_bytes(value))
        # Windows readers can briefly hold a handle without FILE_SHARE_DELETE.
        # Keep the old complete JSON visible, then retry the atomic replacement.
        # Bound the total delay to 150 ms so a busy reader cannot stall the
        # controller's transmit lease renewal indefinitely.
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 4:
                    raise
                time.sleep(.01 * 2**attempt)
    finally:
        tmp.unlink(missing_ok=True)


def _number(value, label, lo, hi, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi}")
    if integer and int(value) != value:
        raise ValueError(f"{label} must be an integer")
    return int(value) if integer else float(value)


# Only operational fields are restored. Source text, notes, paths, armed state,
# diagnostic counters, and unknown keys are never interpreted as commands.
FIELDS = {
    "acquisition": {
        "depth_cm": (2, 40), "win_words": (320, 65535, True),
        "dly_us": (0, 500), "damp_gap_us": (0, 5000),
        "tgc_min": (0, 4095, True), "tgc_max": (0, 4095, True),
        "fs_hz": (40000000, 40000000, True), "n_elem_rx": (48, 48, True)},
    "transmit": {
        "chirp_f0_mhz": (.5, 8), "chirp_f1_mhz": (.5, 8),
        "chirp_us": (1, 40), "n_cycles": (1, 16, True),
        "t_drive_ns": (10, 500), "t_dead_ns": (40, 200),
        "t_settle_us": (4, 40), "t_inhib_us": (4.5, 40),
        "t_ring_us": (0, 50), "n_elem": (1, 48, True)},
    "receive": {"band_f0_mhz": (1, 9), "band_bw_mhz": (1, 12),
                "avg_sweeps": (1, 16, True)},
    "beamformer": {"c_m_s": (1400, 1650), "apod": (0, 1), "cf": (0, 3),
                   "accept_deg": (5, 90), "t0_ns": (-2000, 4000),
                   "R_mm": (40, 120), "pitch_mm": (.2, .6)},
    "display": {"dyn_db": (20, 100), "gain_db": (-40, 40), "curve": (.3, 1),
                "zoom": (.1, 100), "pan_cx": (-10, 10), "pan_cz": (-10, 10),
                "debug_view": (0, 2, True)},
}
BOOLS = {"transmit": ["chirp_on"],
         "receive": ["bandpass_on", "frequency_compounding", "matched_filter",
                     "dejitter_on", "bg_subtract"],
         "beamformer": ["flip_lr"], "display": ["auto_gain", "signed"]}


def validate_settings(document, defaults=None):
    if not isinstance(document, dict):
        raise ValueError("Settings must be a JSON object")
    if not any(section in document for section in FIELDS):
        raise ValueError("No host settings sections found in this file")
    if document.get("settings_schema", 1) != 1:
        raise ValueError("Unsupported settings schema")
    result = copy.deepcopy(defaults or {})
    for section, fields in FIELDS.items():
        given = document.get(section, {})
        if not isinstance(given, dict):
            raise ValueError(f"{section} must be an object")
        target = result.setdefault(section, {})
        for key, bounds in fields.items():
            if key in given:
                if section == "display" and key == "pan_cz" and given[key] is None:
                    target[key] = None
                    continue
                target[key] = _number(given[key], f"{section}.{key}", *bounds)
        for key in BOOLS.get(section, []):
            if key in given:
                if not isinstance(given[key], bool):
                    raise ValueError(f"{section}.{key} must be true or false")
                target[key] = given[key]
    a = result["acquisition"]
    if a.get("tgc_min", 0) > a.get("tgc_max", 4095):
        raise ValueError("TGC minimum exceeds maximum")
    tx = document.get("transmit", {})
    if "single_elem" in tx:
        result["transmit"]["single_elem"] = (None if tx["single_elem"] is None else
            _number(tx["single_elem"], "single_elem", 0, 47, True))
    if "trim_ns" in tx:
        trims = tx["trim_ns"]
        if not isinstance(trims, list) or len(trims) != 48:
            raise ValueError("Transmit trim table must contain 48 entries")
        result["transmit"]["trim_ns"] = [
            _number(v, "trim_ns", -2000, 38950) for v in trims]
    if "dead" in document.get("beamformer", {}):
        ids = document["beamformer"]["dead"]
        if not isinstance(ids, list):
            raise ValueError("dead must be an array of element IDs")
        result["beamformer"]["dead"] = sorted(set(
            _number(v, "dead", 0, 47, True) for v in ids))
    result["transmit"]["armed"] = False  # loading a file never authorizes firing
    return result


def load_settings(path, defaults=None):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Settings file is too large")
    return validate_settings(json.loads(path.read_text(encoding="utf-8-sig")), defaults)


def acquisition_key(settings):
    """A new acquisition epoch is required for changes to actual recorded RF."""
    tx = settings["transmit"]
    value = {"acquisition": {k: settings["acquisition"].get(k)
                             for k in FIELDS["acquisition"]},
             "transmit": {k: tx.get(k) for k in (*FIELDS["transmit"],
                           "chirp_on", "single_elem", "trim_ns")},
             "signed": settings["display"]["signed"]}
    return hashlib.sha256(json_bytes(value)).hexdigest()


def provenance(root):
    root = Path(root)
    names = ["host/tfm_gl_host.py", "host/pulser_ctrl.py", "host/rf_debug.py",
             "host/rf_debug_ui.py", "host/waterfall_host.py",
             "host/bench_host.py", "host/bench_render.py", "host/bench_client.py",
             "host/bench_transport.py", "host/acquisition_timing.py",
             "docs/ultrasound-debug-setup.json", "docs/schematic-connectivity-2026-09-07.md"]
    names += [str(p.relative_to(root)) for p in
              (root / "usb3-tester.srcs/sources_1/new").glob("*.v")]
    files = {}
    for name in names:
        p = root / name
        if p.is_file():
            files[name.replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"source_sha256": files,
            "loaded_fpga_build": "unknown; source hashes do not identify the programmed bitstream",
            "hardware_register_readback": "unavailable on current stream protocol"}


def _write_array(zf, name, a):
    with zf.open(name, "w", force_zip64=True) as stream:
        np.lib.format.write_array(stream, np.asarray(a), allow_pickle=False)


def validate_quality(quality, count):
    if not isinstance(quality, list) or len(quality) != count:
        raise ValueError("Frame quality records do not match the frame count")
    for q in quality:
        if not isinstance(q, dict) or not isinstance(q.get("valid"), bool):
            raise ValueError("Invalid frame-quality record")
        for field in ("valid_elements", "bad_elements", "missing_elements"):
            if field in q:
                ids = q[field]
                if not isinstance(ids, list):
                    raise ValueError(f"{field} must be an element list")
                for e in ids:
                    _number(e, field, 0, 47, True)
                if len(set(ids)) != len(ids):
                    raise ValueError(f"Duplicate elements in {field}")
        if "valid_elements" not in q:
            raise ValueError("Frame-quality record must identify valid elements")


def save_session(path, frames, timestamps, metadata, quality, tx_reference,
                 background=None, progress=None):
    """Stream frozen frames to an atomic archive without stacking the whole cine."""
    count = len(frames)
    if not count:
        raise ValueError("There are no RF frames to save")
    shape = tuple(frames[0].shape)
    if len(shape) != 2 or shape[0] != 48 or not 640 <= shape[1] <= 131070:
        raise ValueError("RF frames must have shape (48, samples)")
    if count * math.prod(shape) * 2 > MAX_RF_BYTES:
        raise ValueError("Selected recording exceeds the session size limit")
    ts = np.asarray(timestamps, dtype="<f8")
    if ts.shape != (count,) or not np.isfinite(ts).all() or np.any(np.diff(ts) < 0):
        raise ValueError("Timestamps must be finite, ordered, and match the frames")
    validate_quality(quality, count)
    reference = np.asarray(tx_reference, dtype="<f4")
    if reference.ndim != 1 or not 1 <= reference.size <= 100000 or not np.isfinite(reference).all():
        raise ValueError("Invalid transmit reference")
    meta = copy.deepcopy(metadata)
    meta.update(schema=SCHEMA, version=VERSION, shape=[count, *shape],
                rf_format="int16 ADC counts, offset decoded, before averaging/filtering",
                wire_tags="not stored; sequence discontinuities recorded per frame",
                timestamp_basis="host receipt monotonic seconds; not hardware shot timestamps")
    validate_settings(meta["acquired_settings"])
    if meta["acquired_settings"]["acquisition"]["win_words"] * 2 != shape[1]:
        raise ValueError("Acquisition sample count does not match RF")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            with zf.open("rf.npy", "w", force_zip64=True) as stream:
                np.lib.format.write_array_header_2_0(stream, {
                    "descr": "<i2", "fortran_order": False, "shape": (count, *shape)})
                for i, frame in enumerate(frames):
                    if frame.shape != shape or frame.dtype != np.int16:
                        raise ValueError("RF shape/dtype changed within the recording")
                    data = np.ascontiguousarray(frame, dtype="<i2").tobytes()
                    stream.write(data)
                    digest.update(data)
                    if progress:
                        progress(i + 1, count)
            meta["rf_sha256"] = digest.hexdigest()
            zf.writestr("metadata.json", json_bytes(meta))
            zf.writestr("quality.json", json_bytes(quality))
            _write_array(zf, "timestamps.npy", ts)
            _write_array(zf, "tx_reference.npy", reference)
            if background is not None:
                if background.shape != shape or not np.isfinite(background).all():
                    raise ValueError("Background reference shape/values invalid")
                _write_array(zf, "background.npy", np.asarray(background, dtype="<f4"))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path


class Session:
    def __init__(self, directory, rf, times, metadata, quality, reference, background):
        self.directory, self.rf, self.timestamps = directory, rf, times
        self.metadata, self.quality = metadata, quality
        self.tx_reference, self.background = reference, background

    def close(self):
        if getattr(self, "rf", None) is not None:
            self.rf._mmap.close()
            self.rf = None
        self.directory.cleanup()


def _map_stored_rf(zf):
    """Map our uncompressed NPY member without making a second large disk copy.

    Return the map plus CRC state for validation during the existing hash pass.
    Compressed/Fortran-order members retain the extraction fallback.
    """
    info = zf.getinfo("rf.npy")
    if info.compress_type != zipfile.ZIP_STORED:
        return None
    with zf.open(info) as src:
        version = np.lib.format.read_magic(src)
        if version not in ((1, 0), (2, 0)):
            return None
        reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                  else np.lib.format.read_array_header_2_0)
        shape, fortran, dtype = reader(src)
        header_size = src.tell()
        if fortran:
            return None
        if (dtype != np.dtype("<i2") or len(shape) != 3 or shape[1] != 48
                or not 640 <= shape[2] <= 131070 or shape[0] < 1):
            raise ValueError("Invalid RF shape/dtype")
        size = math.prod(shape) * dtype.itemsize
        if size > MAX_RF_BYTES or header_size + size != info.file_size:
            raise ValueError("RF member size does not match its array header")
        src.seek(0)
        npy_header = src.read(header_size)
    # ZIP64 stores sizes in an extra field, but its local header still gives
    # the filename/extra lengths needed to locate the member bytes.
    zf.fp.seek(info.header_offset)
    header = zf.fp.read(30)
    if len(header) != 30:
        raise ValueError("Truncated ZIP local header")
    signature, name_size, extra_size = struct.unpack("<4s22xHH", header)
    if signature != b"PK\x03\x04":
        raise ValueError("Invalid ZIP local header")
    offset = info.header_offset + 30 + name_size + extra_size + header_size
    rf = np.memmap(zf.fp, dtype=dtype, mode="r", offset=offset, shape=shape)
    return rf, zlib.crc32(npy_header), info.CRC


def load_session(path):
    directory = tempfile.TemporaryDirectory(prefix="usb3-rf-")
    rf = None
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            allowed = {"rf.npy", "timestamps.npy", "metadata.json", "quality.json",
                       "tx_reference.npy", "background.npy"}
            if len(set(names)) != len(names) or not set(names) <= allowed:
                raise ValueError("Unexpected or duplicate archive entries")
            for name in allowed - {"background.npy"}:
                if name not in names:
                    raise ValueError(f"Missing archive entry: {name}")
            for info in zf.infolist():
                limit = MAX_RF_BYTES + 4096 if info.filename == "rf.npy" else MAX_JSON_BYTES
                if info.file_size > limit:
                    raise ValueError(f"Archive entry too large: {info.filename}")
            meta = json.loads(zf.read("metadata.json"))
            if meta.get("schema") != SCHEMA or meta.get("version") != VERSION:
                raise ValueError("Unsupported RF session format/version")
            validate_settings(meta["acquired_settings"])
            quality = json.loads(zf.read("quality.json"))
            mapped = _map_stored_rf(zf)
            crc = expected_crc = None
            if mapped is not None:
                rf, crc, expected_crc = mapped
            else:
                dest = Path(directory.name) / "rf.npy"
                with zf.open("rf.npy") as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                rf = np.load(dest, mmap_mode="r", allow_pickle=False)
            if (rf.dtype != np.dtype("<i2") or rf.ndim != 3 or rf.shape[1] != 48
                    or not 640 <= rf.shape[2] <= 131070 or rf.shape[0] < 1
                    or list(rf.shape) != meta.get("shape")):
                raise ValueError("Invalid RF shape/dtype")
            if rf.shape[2] != 2 * meta["acquired_settings"]["acquisition"]["win_words"]:
                raise ValueError("RF/acquisition sample-count mismatch")
            digest = hashlib.sha256()
            for frame in rf:
                data = frame.tobytes()
                digest.update(data)
                if crc is not None:
                    crc = zlib.crc32(data, crc)
            if crc is not None and (crc & 0xffffffff) != expected_crc:
                raise zipfile.BadZipFile("Bad CRC-32 for RF member")
            if digest.hexdigest() != meta.get("rf_sha256"):
                raise ValueError("RF checksum mismatch")
            def array(name):
                with zf.open(name) as src:
                    a = np.load(src, allow_pickle=False)
                if a.dtype.kind not in "fiub" or not np.isfinite(a).all():
                    raise ValueError(f"Invalid numeric values in {name}")
                return a
            times, reference = array("timestamps.npy"), array("tx_reference.npy")
            background = array("background.npy") if "background.npy" in names else None
            if times.shape != (len(rf),) or np.any(np.diff(times) < 0):
                raise ValueError("Invalid timestamps")
            validate_quality(quality, len(rf))
            if reference.ndim != 1 or not 1 <= reference.size <= 100000:
                raise ValueError("Invalid transmit reference")
            if background is not None and background.shape != rf.shape[1:]:
                raise ValueError("Invalid background reference shape")
        return Session(directory, rf, times, meta, quality, reference, background)
    except BaseException:
        if rf is not None and hasattr(rf, "_mmap"):
            rf._mmap.close()
        directory.cleanup()
        raise


def diagnostics(frames, quality, fs_hz=40e6, max_frames=64):
    """Full-window metrics on a declared, evenly sampled subset of a recording.

    Temporal residual includes motion/timing variation and must not be called
    electronic noise without a stationary, matched-condition experiment.
    """
    if not len(frames):
        raise ValueError("No RF frames to analyze")
    validate_quality(quality, len(frames))
    indices = np.unique(np.linspace(0, len(frames)-1, min(len(frames), max_frames)).astype(int))
    shape = frames[0].shape
    total = np.zeros(shape, np.float64)
    squares = np.zeros(shape, np.float64)
    peak = np.zeros(shape[0], np.float64)
    clipped = np.zeros(shape[0], np.int64)
    count = np.zeros(shape[0], np.int64)
    gates = [slice(i*shape[1]//4, (i+1)*shape[1]//4) for i in range(4)]
    for idx in indices:
        a = np.asarray(frames[int(idx)], dtype=np.float64)
        valid = quality[int(idx)].get("valid_elements", list(range(shape[0])))
        mask = np.zeros(shape[0], bool)
        mask[valid] = True
        a[~mask] = 0
        total += a
        squares += a*a
        peak = np.maximum(peak, np.max(np.abs(a), axis=1))
        clipped += np.sum((a <= -2048) | (a >= 2047), axis=1)
        count += mask
    divisor = np.maximum(count, 1)[:, None]
    mean = total / divisor
    variance = np.maximum(squares/divisor - mean*mean, 0)
    rows = []
    for e in range(shape[0]):
        rms = float(np.sqrt(np.mean(squares[e]/max(count[e], 1))))
        rows.append({"element": e, "frames_measured": int(count[e]),
                     "peak_counts": float(peak[e]), "rms_counts": rms,
                     "rms_dbfs": 20*math.log10(max(rms/2048, 1e-12)),
                     "clipped_fraction": float(clipped[e]/max(count[e]*shape[1], 1)),
                     "temporal_residual_rms_counts": float(np.sqrt(variance[e].mean())),
                     "quarter_window_rms_counts": [float(np.sqrt(
                         np.mean(squares[e,g]/max(count[e],1)))) for g in gates]})
    return {"frames_total": len(frames), "frames_examined": len(indices),
            "examined_indices": indices.tolist(),
            "degraded_frames_total": sum(not q["valid"] for q in quality),
            "window_us": shape[1]/fs_hz*1e6, "elements": rows,
            "interpretation": "ADC-domain measurements before filtering/TGC removal; temporal residual is not an SNR or electronic-noise estimate. Zero/low response alone does not prove an open element."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    session = load_session(args.session)
    try:
        report = diagnostics(session.rf, session.quality)
        report["acquired_settings"] = session.metadata["acquired_settings"]
        report["context"] = session.metadata.get("context", {})
        report["provenance"] = session.metadata.get("provenance", {})
        target = args.report or args.session.with_suffix(".report.json")
        atomic_json(target, report)
        print(f"Analyzed {report['frames_examined']} of {len(session.rf)} RF frames; report: {target}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
