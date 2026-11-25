#!/usr/bin/env python3
"""Create a replay session with programmed per-element TX trim removed.

The source session remains untouched.  Positive trim delays a transmitted echo,
so the derived trace samples the source at n + trim_samples to move that echo
back to the flat-trim timebase.  The fixed hardware TRIM_BIAS is intentionally
left in place and represented by the replay t0 value.
"""
from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
import rf_debug  # noqa: E402


def shifted_trace(trace, samples):
    index = np.arange(trace.size, dtype=np.float64)
    values = np.interp(index + samples, index, trace, left=0.0, right=0.0)
    return np.rint(np.clip(values, -32768, 32767)).astype(np.int16)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--t0-ns", type=float, default=2000.0,
                        help="fixed hardware trim-bias delay retained in replay")
    args = parser.parse_args()

    session = rf_debug.load_session(args.source.resolve())
    try:
        acquired = session.metadata["acquired_settings"]
        trims_ns = np.asarray(acquired["transmit"]["trim_ns"], dtype=np.float64)
        fs_hz = float(acquired["acquisition"]["fs_hz"])
        shifts = trims_ns * 1e-9 * fs_hz
        frames = []
        for source_frame in session.rf:
            frame = np.empty_like(source_frame)
            for element in range(source_frame.shape[0]):
                frame[element] = shifted_trace(source_frame[element], shifts[element])
            frames.append(frame)

        metadata = copy.deepcopy(session.metadata)
        metadata.pop("schema", None)
        metadata.pop("version", None)
        metadata.pop("shape", None)
        metadata.pop("rf_sha256", None)
        review = copy.deepcopy(metadata.get("review_settings", acquired))
        review["beamformer"]["t0_ns"] = float(args.t0_ns)
        metadata["review_settings"] = review
        metadata["derived_processing"] = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(args.source.resolve()),
            "operation": "fractional linear time shift removing acquired transmit.trim_ns per element",
            "shift_sign": "output[n] = source[n + trim_ns*fs]",
            "retained_common_trim_bias_ns": float(args.t0_ns),
            "source_rf_sha256": session.metadata.get("rf_sha256"),
            "warning": "Derived replay data, not unmodified ADC samples. Use the source session for raw analysis.",
        }
        rf_debug.save_session(
            args.output.resolve(), frames, session.timestamps, metadata,
            copy.deepcopy(session.quality), session.tx_reference,
            None if session.background is None else session.background.copy(),
        )
        print(args.output.resolve())
    finally:
        session.close()


if __name__ == "__main__":
    main()
