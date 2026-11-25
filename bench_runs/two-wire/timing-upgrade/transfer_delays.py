"""Fit acoustic per-element receive-time offsets on a different wire acquisition."""
from compare_timing import ROOT,OUT,load,bf,spectral_rows,render,metrics
import numpy as np
import json

train=ROOT/"bench_runs/phantom-pulse-comparison/one-cycle.rf.npz"
test=ROOT/"gelatin-2-wires.rf.npz"
frames,train_meta,quality=load(train)
assert quality[0]["valid"]
acq=train_meta["acquired_settings"]
fs=acq["acquisition"]["fs_hz"]
assert np.all(np.asarray(acq["transmit"]["trim_ns"])==0)
base=render(frames[0],np.zeros(48),acq["acquisition"]["dly_us"],8,fs)
wire=metrics(base["DAS"],[(2.39,16.16)])["wires"][0]
cx,cz=wire["xz_mm"]
rows=8*np.fft.ifft(spectral_rows(frames[0],fs),n=3240*8,axis=-1)
time=np.arange(rows.shape[1])
theta=(np.arange(48)-23.5)*bf["pitch_mm"]/bf["R_mm"]
dx=cx-bf["R_mm"]*np.sin(theta)
dz=cz-bf["R_mm"]*(np.cos(theta)-1)
dist=np.hypot(dx,dz)
direct=(dx*np.sin(theta)+dz*np.cos(theta))/dist>=np.cos(np.radians(bf["accept_deg"]))
direct[bf["dead"]]=False
pos=(2e-3*dist/bf["c_m_s"]+bf["t0_ns"]*1e-9-acq["acquisition"]["dly_us"]*1e-6)*fs*8
# 0.80 us reference segment centred on the held-in DAS peak.
window=np.arange(-128,129)
wave=np.array([np.interp(p+window,time,row.real) for p,row in zip(pos,rows)])
ref=wave[direct].sum(axis=0)
norm=np.linalg.norm
lag_grid=np.arange(-32,33) # +/-100 ns at 320 MHz.
amp=np.linalg.norm(wave,axis=1)
residuals=np.zeros(48)
used=[]
for i in np.flatnonzero(direct):
    if amp[i] < np.median(amp[direct])*.25:
        continue
    # Leave this element out of the alignment reference to avoid self-correlation.
    other=ref-wave[i]
    traces=np.interp(pos[i]+window[None,:]+lag_grid[:,None],time,rows[i].real)
    corr=(traces@other)/(norm(traces,axis=1)*norm(other)+1e-15)
    j=int(np.argmax(corr))
    if j in (0,len(lag_grid)-1) or corr[j]<.75:
        continue
    residuals[i]=1e9/(fs*8)*lag_grid[j]
    used.append(int(i))
if len(used)<6:
    raise RuntimeError(f"Too few cross-correlated training elements: {used}")
# Remove common and linear components, which the location fit can absorb.
residuals[used]-=np.polyval(np.polyfit(used,residuals[used],1),used)
test_rf,test_meta,quality=load(test)
assert quality[0]["valid"]
acq=test_meta["acquired_settings"]
trims=np.asarray(acq["transmit"]["trim_ns"])
anchors=[(-7.18,18.62),(7.67,20.12)]
results={"train":str(train),"test":str(test),"used":used,"residual_ns":residuals.tolist(),"training_xz_mm":[cx,cz]}
for name,offsets in (("table_only",trims),("acoustic_transfer",trims+residuals)):
    ims=render(test_rf[0],offsets,acq["acquisition"]["dly_us"],8,fs)
    results[name]={k:metrics(v,anchors) for k,v in ims.items()}
(OUT/"transferred-delays.json").write_text(json.dumps(results,indent=2))
print("Training elements:",used)
print("Offsets RMS:",np.sqrt(np.mean(residuals[used]**2)))
for name in ("table_only","acoustic_transfer"):
    print(name,json.dumps(results[name]["CF0.15"],indent=2))
