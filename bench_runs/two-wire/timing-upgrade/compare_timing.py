"""Fractional-delay ablation on measured RF. Run from any directory."""
from pathlib import Path
import json
import sys
import zipfile
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT/"host"))
from bench_render import _width

x = -16+(np.arange(768)+0.5)/24
z = 10+(np.arange(528)+0.5)/24
xx,zz=np.meshgrid(x,z,sparse=True)
shape=(len(z),len(x))
bf=json.loads((ROOT/"host/presets/gelatin-two-wire-best.json").read_text())["beamformer"]

def spectral_rows(rf,fs):
    # Both recordings use 3208 samples; production uses a 3240 point FFT.
    assert rf.shape==(48,3208)
    freq=np.arange(3240)*fs/3240
    def ramp(t):
        return (1-np.cos(np.pi*np.clip(t,0,1)))/2
    filt=2*ramp((freq-1.5e6)/1.05e6)*ramp((7.5e6-freq)/1.05e6)
    return np.fft.fft(rf,n=3240,axis=-1)*filt

def render(rf,trims_ns,gate_us,upsample,fs):
    spectrum=spectral_rows(rf,fs)
    # Only positive frequencies contain energy, so appending high-frequency
    # zeros refines the time grid without altering the original sample values.
    analytic=upsample*np.fft.ifft(spectrum,n=3240*upsample,axis=-1)
    summed=np.zeros(shape,complex)
    power=np.zeros(shape)
    count=np.zeros(shape)
    for i in range(48):
        if i in bf["dead"]:
            continue
        th=(i-23.5)*bf["pitch_mm"]/bf["R_mm"]
        dx=xx-bf["R_mm"]*np.sin(th)
        dz=zz-bf["R_mm"]*(np.cos(th)-1)
        dist=np.hypot(dx,dz)
        accept=(dx*np.sin(th)+dz*np.cos(th))/dist>=np.cos(np.radians(bf["accept_deg"]))
        t=(2e-3*dist/bf["c_m_s"]+1e-9*(bf["t0_ns"]+trims_ns[i])-gate_us*1e-6)*fs
        sig=accept*np.interp(t*upsample,np.arange(analytic.shape[1]),analytic[i],left=0,right=0)
        summed+=sig
        power+=abs(sig)**2
        count+=accept
    das=abs(summed)
    return {"DAS":das,"CF0.15":das*(das**2/np.maximum(count*power,1e-20))**.15}

def db(v):
    return 20*np.log10(np.maximum(v,1e-18))

def metrics(image, anchors):
    stats={"wires":[]}
    for ax,az in anchors:
        core=(abs(xx-ax)<1)&(abs(zz-az)<.70)
        flank=(abs(xx-ax)>=1.4)&(abs(xx-ax)<=5.5)&(abs(zz-az)<=.85)
        r,c=np.unravel_index(np.argmax(np.where(core,image,-1)),shape)
        stats["wires"].append({"xz_mm":[x[c],z[r]],"lat_mm":_width(image[r],x,c),"ax_mm":_width(image[:,c],z,r),
                               "peak_db":db(image[r,c]),"flank95_rel_db":db(np.percentile(image[flank],95)/image[r,c])})
    stats["gel_median_db"]=[db(np.median(image[(abs(xx)<=4)&(zz>=a)&(zz<=b)])) for a,b in [(13,16),(26,29)]]
    return stats

def load(path):
    with np.load(path) as archive:
        rf=archive["rf"]
    with zipfile.ZipFile(path) as archive:
        meta=json.loads(archive.read("metadata.json"))
        quality=json.loads(archive.read("quality.json"))
    return rf,meta,quality

def compare(source,derived,derived_meta):
    results={}
    rf,meta,quality=load(source)
    single=len(rf)>1
    acquired=meta["acquired_settings"]
    trims=np.array(acquired["transmit"]["trim_ns"])
    assert acquired["source"]=="hardware"
    if single:
        assert np.all(trims==0)
    else:
        assert derived_meta["derived_processing"]["source_rf_sha256"]==meta["rf_sha256"]
    for idx in ([0,23,47] if single else [0]):
        assert quality[idx]["valid"]
        key=f"{source.name} frame {idx}"
        cases={"current":(rf[idx] if single else derived[idx],np.zeros(48),1),
               "single-linear":(rf[idx],trims,1),"single-8x":(rf[idx],trims,8)}
        if not single:
            cases["single-16x"]=(rf[idx],trims,16)
        anchors=[(2.39,16.16)] if single else [(-7.18,18.62),(7.67,20.12)]
        summary={}
        for name,(data,delay,factor) in cases.items():
            ims=render(data,delay,acquired["acquisition"]["dly_us"],factor,acquired["acquisition"]["fs_hz"])
            summary[name]={method:metrics(amp,anchors) for method,amp in ims.items()}
        results[key]=summary
        print(key,[(k,[round(w["lat_mm"],4) for w in v["CF0.15"]["wires"]],
                    [round(w["peak_db"],2) for w in v["CF0.15"]["wires"]]) for k,v in summary.items()],flush=True)
    return results

if __name__=="__main__":
    sources=[ROOT/"gelatin-2-wires.rf.npz",ROOT/"bench_runs/phantom-pulse-comparison/one-cycle.rf.npz"]
    derived,derived_meta,_=load(ROOT/"bench_runs/two-wire/gelatin-2-wires-trim-comp.rf.npz")
    results={}
    for source in sources:
        results.update(compare(source,derived,derived_meta))
    (OUT/"metrics.json").write_text(json.dumps(results,indent=2))
