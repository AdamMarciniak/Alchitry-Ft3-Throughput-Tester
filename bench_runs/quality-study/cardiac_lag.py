"""Check whether the axial RF lag on one frame pair predicts the next pair."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.signal import butter, sosfiltfilt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "host"))
from rf_debug import load_session

GATES_MM = (12, 55, 85, 120, 145)
MAX_LAG = 64


def lag_correlations(first, second):
    """Per-element Pearson correlation against each shifted second window."""
    first = first - first.mean(axis=1, keepdims=True)
    first /= np.sqrt(np.sum(first ** 2, axis=1, keepdims=True) + 1e-20)
    columns = []
    for start in range(2 * MAX_LAG + 1):
        shifted = second[:, start:start + first.shape[1]]
        shifted = shifted - shifted.mean(axis=1, keepdims=True)
        columns.append(np.sum(first * shifted, axis=1)
                       / np.sqrt(np.sum(shifted ** 2, axis=1) + 1e-20))
    return np.stack(columns, axis=1)


def summary(rows, speed, sample_rate):
    held_zero, held_predicted, train_peak, best_lag = np.concatenate(rows).T
    reliable = (train_peak >= 0.65) & (abs(best_lag) < MAX_LAG)
    selected = reliable & (abs(best_lag) >= 2)
    result = {
        "element_triplets": len(best_lag),
        "held_zero_lag_ncc_quartiles_all": np.percentile(held_zero, [25, 50, 75]).tolist(),
        "qualifying_training_peaks": int(reliable.sum()),
        "qualifying_nonzero_training_tracks": int(selected.sum()),
        "qualifying_nonzero_fraction": float(selected.mean()),
    }
    if selected.any():
        result.update(
            held_zero_lag_ncc_median_selected=float(np.median(held_zero[selected])),
            held_predicted_lag_ncc_median_selected=float(np.median(held_predicted[selected])),
            train_abs_lag_equivalent_range_mm_quartiles=(
                np.percentile(abs(best_lag[selected]), [25, 50, 75]) * speed * 1000
                / (2 * sample_rate)).tolist(),
        )
    return result


def check(session):
    acquired = session.metadata["acquired_settings"]
    acquisition = acquired["acquisition"]
    sample_rate = acquisition["fs_hz"]
    speed = acquired["beamformer"]["c_m_s"]
    offset = acquisition["dly_us"] * 1e-6
    dead = acquired["beamformer"]["dead"]
    active = np.array([i for i in range(session.rf.shape[1]) if i not in dead])
    starts = np.linspace(0, len(session.rf) - 3, 24, dtype=int)
    sos = butter(4, (2e6, 5e6), "bandpass", fs=sample_rate, output="sos")
    data = {z: [] for z in GATES_MM}
    for i in starts:
        if not all(session.quality[j]["valid"] for j in (i, i+1, i+2)):
            raise ValueError(f"Invalid frame in triplet starting at {i}")
        v = sosfiltfilt(sos, np.asarray(session.rf[i:i+3, active, :], float), axis=-1)
        for z in GATES_MM:
            first, last = np.rint((2*np.array([z-2, z+2])*1e-3/speed - offset)
                                  * sample_rate).astype(int)
            if first - MAX_LAG < 0 or last + MAX_LAG > v.shape[-1]:
                raise ValueError(f"Gate at {z} mm exceeds RF support")
            train = lag_correlations(v[0, :, first:last], v[1, :, first-MAX_LAG:last+MAX_LAG])
            held = lag_correlations(v[1, :, first:last], v[2, :, first-MAX_LAG:last+MAX_LAG])
            ix = np.argmax(train, axis=1)
            rows = np.arange(len(active))
            data[z].append(np.stack([held[:, MAX_LAG], held[rows, ix], train[rows, ix],
                                     ix - MAX_LAG], axis=-1))
    return {
        "source_rf_sha256": session.metadata["rf_sha256"],
        "source_rf_shape": list(session.rf.shape),
        "sample_rate_hz": sample_rate,
        "raw_sample_interval_ns": 1e9/sample_rate,
        "host_mean_sweep_interval_ms": float(np.mean(np.diff(session.timestamps)) * 1e3),
        "timestamp_basis": session.metadata["timestamp_basis"],
        "triplet_start_frames": starts.tolist(),
        "excluded_elements": dead,
        "processing": "4th-order Butterworth 2-5 MHz forward/backward on signed RF per physical row. Pearson correlation in 4-mm windows. Train on one frame pair, then use its lag directly on the next pair. Pairs share the middle frame. Positive lag searches later samples in frame two. Train selection uses peak >= 0.65 and magnitude 2 through 63 samples. All gates are equivalent pulse-echo ranges using the recorded sound speed and receive offset, without a lens correction.",
        "sound_speed_m_s": speed,
        "receive_start_us": acquisition["dly_us"],
        "max_lag_samples": MAX_LAG,
        "gates_mm": {str(z): summary(rows, speed, sample_rate) for z, rows in data.items()},
        "interpretation": "Measures predictability of per-row inter-sweep axial lag. Coherent reverberation, speckle, probe and target motion and noise all contribute. This is a replay diagnostic. The recording contains no independent ground truth for per-shot motion or acoustic velocity.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?",
                        default=ROOT / "bench_runs/apical-4ch-20261124/heart-apical-reviewed.rf.npz")
    parser.add_argument("--output", type=Path, default=HERE / "cardiac-lag.json")
    args = parser.parse_args()
    session = load_session(args.source)
    try:
        result = check(session)
        result["input"] = str(args.source.resolve())
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    finally:
        session.close()
