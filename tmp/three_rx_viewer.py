"""One-shot verification in the interactive TFM viewer; hands control back to its normal UI."""
from pathlib import Path
from datetime import datetime, timezone
import sys, os, json, time, copy, traceback
import numpy as np
root=Path(__file__).resolve().parents[1]
out=root/'bench_runs/three-position-rx'
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

cfg=json.loads((out/'pre-upgrade-settings.json').read_text())
def start():
    try:
        win.debug_apply(json.loads((root/'bench_runs/phantom-pulse-comparison/current-custom.json').read_text()))
        win.debug_apply(cfg)
        win.apply_method(6)
        win.debug_note.setText('1 mm wire in psyllium gelatin | three-position RX')
        win.debug_tick()
        info=query_firmware(h,'5f216de5')
        check_configuration(h,win,info)
        verify.info=info
        # Keep the existing hardware watchdog active while the viewer responds.
        win.lease_timer=h.QTimer(win)
        win.lease_timer.timeout.connect(lambda: h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew'))
        win.lease_timer.start(400)
        h.send_cmd(h.cmd(0x1e,2000),'bench_lease_renew')
        win.cb_arm.setChecked(True)
        win.debug_tick()
        verify.deadline=time.monotonic()+35
        win.switch_queue=[3,6]
        h.QTimer.singleShot(1600,cycle)
    except BaseException:
        print('LIVE FAILURE',h.stats,'cb',win.cb_arm.isChecked(), flush=True)
        traceback.print_exc()
        win.cb_arm.setChecked(False)
def cycle():
    try:
        if time.monotonic()>verify.deadline:
            raise RuntimeError('Live method switch timed out')
        if h.cine.status()[0] < 12:
            h.QTimer.singleShot(120,cycle)
            return
        with h.cine.lk:
            q=h.cine.quality[-1]
        if not q['valid'] or not h.pulser.arm:
            raise RuntimeError('Live method did not acquire a verified sweep')
        print('LIVE DROP-DOWN',win.method_combo.currentText(),h.live_buf.shape,flush=True)
        if win.switch_queue:
            index=win.switch_queue.pop(0)
            win.method_combo.setCurrentIndex(index)
            win.method_combo.activated.emit(index)
            if not h.pulser.arm or win.method_combo.currentIndex()!=index:
                raise RuntimeError(win.debug_label.text())
            h.QTimer.singleShot(600,cycle)
            return
        h.QTimer.singleShot(400,verify)
    except BaseException:
        print('LIVE FAILURE',h.stats,'cb',win.cb_arm.isChecked(), flush=True)
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
        print('LIVE FAILURE',h.stats,'cb',win.cb_arm.isChecked(), flush=True)
        traceback.print_exc()
        win.cb_arm.setChecked(False)
win.showMaximized()
h.QTimer.singleShot(1400,start)
sys.exit(app.exec())



