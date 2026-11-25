"""One-shot verification in the interactive TFM viewer; hands control back to its normal UI."""
from pathlib import Path
from datetime import datetime, timezone
import sys, os, json, time, copy, traceback
import numpy as np
root=Path(__file__).resolve().parents[1]
out=root/'bench_runs/gelatin-20261124'
sys.path.insert(0,str(root/'host'))
sys.argv=[str(root/'host/tfm_gl_host.py')]
from PySide6.QtGui import QSurfaceFormat
fmt=QSurfaceFormat()
fmt.setVersion(3,3)
fmt.setProfile(QSurfaceFormat.CoreProfile)
fmt.setDepthBufferSize(0)
fmt.setStencilBufferSize(0)
fmt.setSwapInterval(0)
QSurfaceFormat.setDefaultFormat(fmt)
import tfm_gl_host as h, rf_debug as files
from bench_transport import query_firmware,check_configuration
if not h.HW:
    raise SystemExit('USB unavailable')
app=h.QApplication(sys.argv)
app.setStyleSheet(h.APP_QSS)
class PhantomViewer(h.Main):
    def closeEvent(self,event):
        if not self.debug_jobs and hasattr(self,'lease_timer'):
            self.lease_timer.stop()
            h.pulser.set_arm(False)
            h.send_cmd(h.cmd(0x1e,0),'bench_lease_release')
        super().closeEvent(event)
win=PhantomViewer()

cfg=json.loads((root/'host/presets/gelatin-wire-19mm.json').read_text())
def start():
    try:
        win.debug_apply(cfg)
        win.debug_note.setText('Wire and psyllium gelatin, validated live preset')
        win.debug_tick()
        info=query_firmware(h)
        check_configuration(h,win,info)
        verify.info=info
        # Keep the existing hardware watchdog active while the viewer responds.
        win.lease_timer=h.QTimer(win)
        win.lease_timer.timeout.connect(lambda: h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew'))
        win.lease_timer.start(400)
        h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
        win.cb_arm.setChecked(True)
        win.debug_tick()
        win.showMaximized()
        verify.deadline=time.monotonic()+15
        h.QTimer.singleShot(2000,verify)
    except BaseException:
        traceback.print_exc()
        win.cb_arm.setChecked(False)
def verify():
    try:
        count=h.cine.status()[0]
        if count<48 or not win.scene.gl.isValid():
            if time.monotonic()>verify.deadline:
                raise RuntimeError(f'Live verification timed out, {count} sweeps')
            h.QTimer.singleShot(300,verify)
            return
        with h.cine.lk:
            last=list(h.cine.buf)[-48:]
            raw=[a.copy() for _,a in last]
            quality=copy.deepcopy(list(h.cine.quality)[-48:])
        if not all(q['valid'] for q in quality):
            if time.monotonic()>verify.deadline:
                raise RuntimeError('No fully valid verification batch')
            h.QTimer.singleShot(200,verify)
            return
        ts=np.array([t for t,_ in last])
        actual=h.settings_snapshot(win,win.debug_note.text())
        meta={'created_utc':datetime.now(timezone.utc).isoformat(),'acquired_settings':actual,
              'review_settings':actual,'context':{'note':actual['note']},'provenance':win.debug_source,
              'firmware_readback_before_arm':verify.info}
        files.save_session(out/'final-live.rf.npz',raw,ts-ts[0],meta,quality,h.mf_reference())
        win.do_capture()
        if win.last is None or not h.render_capture(win.last).save(str(out/'final-live-bmode.png')):
            raise RuntimeError('Native B-mode capture failed')
        if not win.grab().save(str(out/'final-live-viewer.png')):
            raise RuntimeError('Viewer screenshot failed')
        files.atomic_json(out/'final-live-settings.json',actual)
        print('LIVE VERIFIED',actual['summary'],flush=True)
    except BaseException:
        traceback.print_exc()
        win.cb_arm.setChecked(False)
start()
sys.exit(app.exec())



