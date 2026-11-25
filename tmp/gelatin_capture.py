from pathlib import Path
import sys, os, copy, time, json, traceback
from datetime import datetime, timezone
import numpy as np
root = Path(__file__).resolve().parents[1]
out = root/'bench_runs/gelatin-20261124'
sys.path.insert(0, str(root/'host'))
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.argv=[str(root/'host/tfm_gl_host.py')]
import tfm_gl_host as h
import rf_debug as files
from bench_transport import query_firmware, check_configuration
if not h.HW:
    raise SystemExit('FTDI not available; no acquisition')
app=h.QApplication(sys.argv)
win=h.Main()
try:
    with_session=files.load_session(root/'host/wire_in_gelatin.rf.npz')
    base=copy.deepcopy(with_session.metadata['acquired_settings'])
    with_session.close()
    win.debug_apply(base)
    # Verify that the connected board supports the bounded acquisition lease.
    info=query_firmware(h)
    print('identity:', info, flush=True)
    for name, change in [('baseline',{}),('near-gain',{'tgc_min':1100}),('flat-gain',{'tgc_min':1700,'tgc_max':2100})]:
        settings=copy.deepcopy(base)
        settings['acquisition'].update(change)
        win.debug_apply(settings)
        win.debug_tick()
        info=query_firmware(h)
        check_configuration(h,win,info)
        try:
            h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
            win.cb_arm.setChecked(True)
            win.debug_tick()
            start=renew=time.monotonic()
            while time.monotonic()-start < 10:
                app.processEvents()
                if time.monotonic()-renew > .25:
                    h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
                    renew=time.monotonic()
                if h.cine.status()[0]>=48:
                    break
                time.sleep(.015)
            with h.cine.lk:
                items=[(t,a.copy(),copy.deepcopy(q)) for (t,a),q in zip(h.cine.buf,h.cine.quality)][-48:]
            actual=h.settings_snapshot(win)
        finally:
            win.cb_arm.setChecked(False)
            h.send_cmd(h.cmd(0x1e,0),'bench_lease_release')
        if len(items)!=48 or not all(q['valid'] for _,_,q in items):
            raise RuntimeError(f'{name}: invalid frame batch, count={len(items)}, stats={h.stats}')
        raw=[item[1] for item in items]
        times=np.array([item[0] for item in items])
        quality=[item[2] for item in items]
        meta={'created_utc':datetime.now(timezone.utc).isoformat(),'acquired_settings':actual,'review_settings':actual,
              'firmware_readback_before_arm':info,'context':{'note':'Stationary 1 mm wire in two-layer psyllium gelatin.'},
              'provenance':win.debug_source}
        files.save_session(out/(name+'.rf.npz'),raw,times-times[0],meta,quality,h.mf_reference())
        print(name,len(items),actual['summary'],flush=True)
finally:
    win.close()
