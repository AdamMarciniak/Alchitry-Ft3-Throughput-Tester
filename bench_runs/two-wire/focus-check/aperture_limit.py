"""Illustrative point response for each wire's actual admitted aperture."""
from pathlib import Path
import json
import numpy as np


out = Path(__file__).resolve().parent
root = out.parents[2]
with np.load(root/'gelatin-2-wires.rf.npz') as arc:
    raw = arc['rf'][0]
    metadata = json.loads(arc['metadata.json'])
acquired = metadata['acquired_settings']
bf = json.loads((root/'host/presets/gelatin-two-wire-best.json').read_text())['beamformer']
fs = acquired['acquisition']['fs_hz'] * 1e-6
gate = acquired['acquisition']['dly_us']
trim = np.array(acquired['transmit']['trim_ns']) * .001
angles = (np.arange(48)-23.5)*bf['pitch_mm']/bf['R_mm']
ex = bf['R_mm'] * np.sin(angles)
ez = bf['R_mm'] * (np.cos(angles)-1.)
alive = ~np.isin(np.arange(48), bf['dead'])
c = bf['c_m_s'] * .001
freq = np.arange(3240)*fs/3240


def ramp(t):
    return .5 - .5*np.cos(np.pi*np.clip(t,0,1))


def half_amplitude_width(values, grid):
    mid = np.argmax(values)
    y = values / values[mid]
    left = np.where(y[:mid] <= .5)[0][-1]
    right = np.where(y[mid:] <= .5)[0][0]+mid
    low = np.interp(.5,y[left:left+2],grid[left:left+2])
    high = np.interp(.5,y[[right,right-1]],grid[[right,right-1]])
    return float(high-low)


def paths(x,z):
    dx = x[:,None]-ex
    dz = z-ez
    d = np.hypot(dx,dz)
    cos_angle = (dx*np.sin(angles)+dz*np.cos(angles))/d
    return 2*d/c, (cos_angle>=np.cos(np.radians(bf['accept_deg']))) & alive


h = 2*ramp((freq-1.5)/1.05)*ramp((7.5-freq)/1.05)
analytic = np.fft.ifft(h*np.fft.fft(raw,n=3240,axis=-1),axis=-1)
results = dict(source_rf_sha256=metadata['rf_sha256'],
               assumptions='Gaussian 0.39 us envelope, measured center frequency, fixed point target, recorded trim-corrected sample magnitude at target for the amplitude-weighted variant; model beamformed with rectangular aperture, plain DAS, and no coherence multiplication',
               wires=[])
for x,z,f in [(-7.1458333,18.6458333,3.984375),(7.7291667,20.1041667,4.0625)]:
    origin, active = paths(np.array([x]),z)
    t = (origin[0]+bf['t0_ns']*.001+trim-gate)*fs
    amplitudes = np.array([abs(np.interp(t[i],np.arange(analytic.shape[1]),analytic[i])) for i in range(48)])
    grid = np.linspace(-1.5,1.5,3001)
    search, accepted = paths(x+grid,z)
    diff = search-origin
    analytic_pulse = np.exp(2j*np.pi*f*diff)*np.exp(-4*np.log(2)*(diff/.39)**2)
    kernel = analytic_pulse*(active&accepted)
    equal = abs(kernel.sum(axis=1))
    measured = abs((kernel*amplitudes).sum(axis=1))
    results['wires'].append(dict(xz_mm=[x,z],MHz=f,admitted=int(active.sum()),
             span_mm=float(np.ptp(ex[active[0]])),uniform_response_width_mm=half_amplitude_width(equal,grid),
             measured_amplitude_response_width_mm=half_amplitude_width(measured,grid)))
encoded = json.dumps(results, indent=2)
print(encoded)
(out/'aperture_limit.json').write_text(encoded)
