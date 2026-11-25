"""Measure stationary echo repeatability from earlier multi-frame phantom recordings."""
from pathlib import Path
import json
import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt


out = Path(__file__).resolve().parent
root = out.parents[2]


def timing(path):
    with np.load(path) as arc:
        m = json.loads(arc['metadata.json'])
        valid = [q['valid'] for q in json.loads(arc['quality.json'])]
        raw = arc['rf'][valid, :, :]
    a = m['acquired_settings']['acquisition']
    fs = a['fs_hz'] * 1e-6
    times = np.arange(raw.shape[2]) / fs + a['dly_us']
    # One-cycle and chirped recordings use the same receive frequency band.
    all_rows = sosfiltfilt(butter(4, [1.5, 6.5], fs=fs, btype='bandpass', output='sos'),
                           raw.astype(float), axis=2)
    ref = all_rows[:8].mean(axis=0)
    eval_rows = all_rows[8:]
    # Follow the highest early echo in each active row. This is a timing test,
    # so both reference and test use the same fixed spatial/sample window.
    indices = np.where((times >= 20) & (times <= 32))[0]
    centers = indices[np.argmax(abs(hilbert(ref, axis=1))[:, indices], axis=1)]
    channels = np.array([i for i in range(48) if i not in (25, 46)])
    tests = {}
    for key in ('early_echo', 'deep_gel'):
        shifts, correlations = [], []
        for ch in channels:
            if key == 'early_echo':
                start, end = centers[ch] - 50, centers[ch] + 51
            else:
                start, end = np.where((times >= 38) & (times <= 46))[0][[0,-1]]
            r = ref[ch, start:end].copy()
            r -= r.mean()
            cc = []
            for lag in range(-6, 7):
                y = eval_rows[:, ch, start+lag:end+lag].copy()
                y -= y.mean(axis=1, keepdims=True)
                cc.append((y @ r)/(np.linalg.norm(r) * np.linalg.norm(y, axis=1)))
            cc = np.array(cc).T
            peak = np.argmax(cc, axis=1)
            frame = np.arange(len(peak))
            left, right = np.clip(peak - 1, 0, 12), np.clip(peak + 1, 0, 12)
            mid = cc[frame, peak]
            frac = .5 * (cc[frame,left] - cc[frame,right]) / (cc[frame,left]+cc[frame,right]-2*mid)
            shifts.append((peak-6+frac)*(1000/fs))
            correlations.append(mid)
        lags = np.array(shifts).T
        corr = np.array(correlations).T
        ok = (corr >= .95) & np.isfinite(lags) & (abs(lags) < 137.5)
        common = np.nanmedian(np.where(ok, lags, np.nan), axis=1)
        def metrics(data):
            return dict(rms_ns=float(np.sqrt(np.mean(data**2))),
                        p95_abs_ns=float(np.percentile(abs(data), 95)))
        tests[key] = dict(accepted=int(ok.sum()), total=ok.size,
                          median_peak_correlation=float(np.median(corr)),
                          lag_to_reference=metrics(lags[ok]),
                          frame_median_lag_to_reference=metrics(common[np.isfinite(common)]),
                          after_frame_median_removal=metrics((lags-common[:,None])[ok]))
    return dict(source=str(path.relative_to(root)), source_rf_sha256=m['rf_sha256'],
                reference_frames=8, evaluation_frames=len(eval_rows), stats=tests)


if __name__ == '__main__':
    folders = ['phantom-pulse-comparison/one-cycle', 'gelatin-20261124/verified-live']
    results = [timing(root / 'bench_runs' / (folder+'.rf.npz')) for folder in folders]
    encoded = json.dumps(results,indent=2,allow_nan=False)
    print(encoded)
    (out / 'repeat_timing.json').write_text(encoded)
