from pathlib import Path
import sys, os, copy, time, json
from datetime import datetime, timezone
import numpy as np
root = Path(__file__).resolve().parents[1]
out = root/'bench_runs/three-position-rx'
out.mkdir(exist_ok=True, parents=True)
sys.path.insert(0,str(root/'host'))
os.environ['QT_QPA_PLATFORM']='offscreen'
indices = [int(i) for i in sys.argv[1:]] or [0,1,2,3,4,5,0]
sys.argv=[str(root/'host/tfm_gl_host.py')]
import tfm_gl_host as h, rf_debug as files, pulse_methods as pm
from bench_transport import query_firmware, check_configuration
if not h.HW: raise RuntimeError('Physical acquisition USB unavailable')
build=json.loads((root/'bench_runs/builds/three-rx-1/manifest.json').read_text())['runtime_build_id']
base=files.load_settings(out/'pre-upgrade-settings.json')
base=pm.profile_settings(base, pm.CHIRP)
late=pm.profile_settings(base, pm.MULTI_RX)['acquisition']['dly_us']
app=h.QApplication(sys.argv)
win=h.Main()
names=['current','one-cycle','two-cycle','broad-chirp','golay','neighbor']
try:
    win.debug_apply(base)
    for name,index,delay in [('broad',3,5),('broad-matched',3,late),('three-rx',6,late),
                             ('broad-matched-repeat',3,late),('three-rx-repeat',6,late)]:
        win.apply_method(index)
        trial=h.settings_snapshot(win)
        trial['acquisition']['dly_us']=delay
        win.debug_apply(trial)
        info=query_firmware(h,build)
        check_configuration(h,win,info)
        if not info['multi_rx'] or not info['pulse_methods'] or info['shot_method']!=h.pulser.shot_method:
            raise RuntimeError(f'Wrong method readback {info}')
        win.debug_tick()
        print('ARMING',name,info,flush=True)
        try:
            if os.getenv('PHANTOM_RESET_FAULT')=='1':
                h.pulser.clear_fault()
                time.sleep(.05)
            h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
            win.cb_arm.setChecked(True)
            win.debug_tick()
            print('ARM state',h.pulser.arm,'verified',win.method_verified,'checked',win.cb_arm.isChecked(),flush=True)
            start=renew=time.monotonic()
            while time.monotonic()-start<12:
                app.processEvents()
                if time.monotonic()-renew>.25:
                    h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
                    renew=time.monotonic()
                if h.cine.status()[0]>=54: break
                time.sleep(.01)
            with h.cine.lk:
                items=[(t,a.copy(),copy.deepcopy(q)) for (t,a),q in zip(list(h.cine.buf)[-48:],list(h.cine.quality)[-48:])]
            actual=h.settings_snapshot(win)
        finally:
            win.cb_arm.setChecked(False)
            h.send_cmd(h.cmd(0x1e,0),'bench_lease_release')
        if len(items)!=48 or not all(q['valid'] for _,_,q in items):
            raise RuntimeError(f'{name}: invalid capture; count={len(items)} stats={h.stats}')
        ts=np.array([t for t,_,_ in items])
        meta=dict(created_utc=datetime.now(timezone.utc).isoformat(),acquired_settings=actual,review_settings=actual,
                  firmware_readback_before_arm=info,context=dict(note='1 mm wire in stationary two-layer psyllium gelatin',method=pm.PROFILES[index]),
                  provenance=win.debug_source)
        files.save_session(out/(name+'.rf.npz'),[a for _,a,_ in items],ts-ts[0],meta,[q for _,_,q in items],h.mf_reference())
        print('SAVED',name,items[0][1].shape,'sweeps/s',round(47/(ts[-1]-ts[0]),1),flush=True)
        if index==6:
            paths=items[-1][1].reshape(48,3,-1)
            assert not np.any(paths[0,1]) and not np.any(paths[47,2])
            assert np.all(np.std(paths[1:47],axis=2)>0)
            assert sum(q['valid'] for _,_,q in items)==48
finally:
    win.close()
