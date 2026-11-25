"""Replay physical three-position captures with one direction per adjacent pair.

The counterfactual copies the surviving trace into its partner's slot to retain
the original aggregate weights, taper, acceptance, geometry and delay model.
It does not predict hardware-switching or inter-shot-motion changes.
"""
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.argv = ["tfm_gl_host.py", "sim"]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import tfm_gl_host as h
import rf_debug
from bench_render import Renderer, wire_metrics

BOX = [-17, 17, 8, 52]
W, H = 442, 572
X = BOX[0] + (np.arange(W) + .5) / 13
Z = BOX[2] + (np.arange(H) + .5) / 13
GEL = np.ix_((Z > 29) & (Z < 37), abs(X) < 5.5)
WIRE = [0.5, 3, 16.8, 19]
ANCHOR = [1.73,17.5]
LATERAL = abs(X[None,:] - ANCHOR[0])
FAR = (LATERAL >= 7) & (LATERAL <= 15) & (abs(Z[:,None]-ANCHOR[1]) < 1.5)


def db(ratio):
    return float(20 * np.log10(max(float(ratio), 1e-12)))


def direction_test(analytic, n, pairs):
    # Zero-lag complex correlation after the commanded matched filter and band
    # pass. Report its signed real part so a constant phase error is penalized.
    channels = analytic.reshape(48, 3, n, 2)
    a = channels[pairs,2,:,0] + 1j * channels[pairs,2,:,1]
    b = channels[pairs+1,1,:,0] + 1j * channels[pairs+1,1,:,1]
    center = channels[pairs,0,:,0] + 1j * channels[pairs,0,:,1]
    shifted = np.roll(b, len(pairs)//2, axis=0)
    range_mm = (h.state["dly_us"] + np.arange(n)/40) * h.state["c"] / 2000
    result = {}
    for lo, hi in [(16.8,22),(23,40)]:
        gate = (range_mm>lo) & (range_mm<hi)
        A, B = a[:,gate], b[:,gate]
        na, nb = np.linalg.norm(A,axis=1), np.linalg.norm(B,axis=1)
        cross = np.sum(A.conj()*B, axis=1)/(na*nb)
        def real_correlation(other):
            other=other[:,gate]
            return float(np.median((np.sum(A.conj()*other,axis=1) /
                                    (na*np.linalg.norm(other,axis=1))).real))
        result[f"{lo}-{hi} nominal range mm"] = dict(
            real_ncc_p10_median=np.percentile(cross.real,[10,50]).tolist(),
            own_center_real_ncc_median=real_correlation(center),
            unrelated_pair_real_ncc_median=real_correlation(shifted),
            rms_gain_abs_difference_db_median=float(np.median(abs(20*np.log10(na/nb)))),
        )
    return result


def run(ren, win, name):
    path = ROOT / "bench_runs/three-position-rx" / (name+".rf.npz")
    s = rf_debug.load_session(path)
    try:
        cfg = s.metadata["acquired_settings"]
        assert cfg["source"]=="hardware" and cfg["transmit"]["shot_method"]==3
        assert set(cfg["beamformer"]["dead"])=={25,46} and max(map(abs,cfg["transmit"]["trim_ns"]))==0
        win.debug_apply(cfg,replay=True)
        h.recorded_tx_reference=s.tx_reference
        h.state.update(debug_view=1)
        n=h.cfg["samps"]
        pairs=np.array([e for e in range(47) if e not in (25,46) and e+1 not in (25,46)])
        output=[]
        for frame in range(len(s.rf)):
            assert s.quality[frame]["valid"]
            analytic=h.prepare_analytic(s.rf[frame],n)
            rows=analytic.reshape(48,3,n,2)
            trial={"frame":frame,"paired_RF":direction_test(analytic,n,pairs),"images":{}}
            for mode in ("original","lower_TX","upper_TX"):
                modified=rows.copy()
                if mode=="lower_TX":
                    modified[pairs+1,1]=rows[pairs,2]
                elif mode=="upper_TX":
                    modified[pairs,2]=rows[pairs+1,1]
                mag,_=ren.render(modified.reshape(144,n,2),BOX,W,H)
                if mode=="original":
                    original=mag
                metrics=wire_metrics(mag,BOX,WIRE,ANCHOR)
                trial["images"][mode]=dict(
                    wire_lateral_mm=metrics["lateral_width_6db_mm"],
                    wire_axial_mm=metrics["axial_width_6db_mm"],
                    wire_peak=metrics["peak"],
                    offaxis_p95_relative_db=db(np.percentile(mag[FAR],95)/metrics["peak"]),
                    gel_envelope_correlation=float(np.corrcoef(mag[GEL].ravel(),original[GEL].ravel())[0,1]),
                    gel_relative_rms_difference=float(np.linalg.norm(mag[GEL]-original[GEL])/np.linalg.norm(original[GEL])),
                )
            output.append(trial)
        return dict(rf_sha256=s.metadata["rf_sha256"],path=str(path.relative_to(ROOT)),n_frames=len(s.rf),trials=output)
    finally:
        s.close()


if __name__=="__main__":
    app=h.QApplication(sys.argv)
    window=h.Main()
    renderer=Renderer(h)
    try:
        records={name:run(renderer,window,name) for name in ("three-rx","three-rx-repeat")}
        rf_debug.atomic_json(HERE/"results.json",records)
        for name, result in records.items():
            trials=result["trials"]
            print(name, len(trials), "single-frame comparisons per direction")
    finally:
        h.stats["alive"]=False
        renderer.close()
        window.close()
