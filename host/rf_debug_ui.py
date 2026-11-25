"""Debug-workflow UI for tfm_gl_host; the portable format lives in rf_debug."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (QPushButton, QLabel, QComboBox, QLineEdit,
                               QFileDialog, QMessageBox)
import rf_debug as files
import pulse_methods


class DebugMixin:
    def debug_init(self, runtime, layout):
        self.g = runtime
        self.debug_session = None
        self.debug_offline = False
        self.debug_loading = False
        self.debug_dirty = True
        self.debug_key = None
        self.debug_epoch = None
        self.debug_review_quality = []
        self.debug_live_settings = None
        self.debug_jobs = []
        self.debug_results = []
        self.debug_events = copy.deepcopy(runtime["debug_startup_commands"])
        self.debug_run_id = 0
        self.debug_source = files.provenance(Path(runtime["__file__"]).resolve().parent.parent)
        setup_path = Path(runtime["__file__"]).resolve().parent.parent / "docs/ultrasound-debug-setup.json"
        try:
            self.debug_setup = json.loads(setup_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.debug_setup = {"profile_unavailable": str(exc)}
        self.debug_live_title = self.windowTitle()
        self.debug_saved_trim = list(runtime["pulser"].trim_ns)
        runtime["debug_command_hook"] = self.debug_command
        for text, fn in (("save RF…", self.debug_save_rf), ("open RF…", self.debug_open_rf),
                         ("load settings…", self.debug_load_settings),
                         ("new live run", self.debug_new_live),
                         ("12 cm fast", self.debug_fast12),
                         ("RF report…", self.debug_report)):
            button = QPushButton(text)
            if text == '12 cm fast':
                button.setToolTip('Prepare a 12 cm / 48-element / 50 us gap candidate, averaging 1.\n'
                    'Keeps the waveform and switch timing floors; preserves TGC slope when shortening depth.\n'
                    'Checks the FPGA capture-ready capability and leaves PULSER RUN off.\n'
                    'Higher firing rate increases average transmitted energy; validate in water before on-body use.')
            button.clicked.connect(fn)
            layout.addWidget(button)
        self.method_base = None
        self.method_verified = True
        self.method_combo = QComboBox()
        self.method_combo.setAccessibleName("Acquisition and pulse method")
        self.method_combo.addItems(pulse_methods.PROFILES)
        self.method_combo.setItemData(pulse_methods.FAST17,
            "Repeats one fixed group of 24 live positions across the full probe at 17 cm. "
            "Every image uses the same aperture, preventing alternating-aperture ghosting. "
            "The FPGA uses its ordinary pulse-echo sequence.",
            Qt.ItemDataRole.ToolTipRole)
        self.method_combo.setItemData(pulse_methods.MULTI_RX,
            "Repeats the broad chirp for the center, left and right receivers. "
            "The receive gate opens after the switch settles. One full aperture takes 142 shots.",
            Qt.ItemDataRole.ToolTipRole)
        self.method_combo.setToolTip("Choose the firing and receive sequence. A live switch starts a new RF epoch.")
        self.method_combo.activated.connect(self.select_method)
        layout.addWidget(self.method_combo)
        self.debug_mode = QComboBox()
        self.debug_mode.addItems(["weighted image", "ordinary DAS", "coherence map"])
        self.debug_mode.setToolTip("Ordinary DAS bypasses coherence weighting. Coherence map shows CF from black=0 to white=1. Both diagnostic views use the full receive band and temporarily bypass frequency compounding.")
        self.debug_mode.currentIndexChanged.connect(self.debug_set_mode)
        layout.addWidget(self.debug_mode)
        self.debug_trim_button = QPushButton("use flat trim")
        self.debug_trim_button.clicked.connect(self.debug_toggle_trim)
        layout.addWidget(self.debug_trim_button)
        self.debug_note = QLineEdit()
        self.debug_note.setPlaceholderText("Test context: target, distance, water temperature, HV, changes…")
        layout.addWidget(self.debug_note, 1)
        self.debug_label = QLabel("Preparing a new acquisition run")
        self.debug_label.setMaximumWidth(310)
        layout.addWidget(self.debug_label)
        self.debug_tick()

    def apply_method(self, index):
        if self.debug_offline or self.g["state"]["frozen"] or self.debug_jobs:
            raise ValueError("Return to live acquisition before switching pulse methods")
        g = self.g
        current = g["settings_snapshot"](self)
        if self.method_base is None:
            self.method_base = copy.deepcopy(current)
        # Restore only fields controlled by this selector. Preserve unrelated live edits.
        baseline = copy.deepcopy(current)
        for key in ("shot_method", "chirp_on", "chirp_f0_mhz", "chirp_f1_mhz",
                    "chirp_us", "n_cycles", "t_drive_ns", "t_dead_ns"):
            baseline["transmit"][key] = self.method_base["transmit"].get(key, 0)
        baseline["acquisition"]["dly_us"] = self.method_base["acquisition"]["dly_us"]
        baseline["receive"]["matched_filter"] = self.method_base["receive"]["matched_filter"]
        if current["transmit"]["shot_method"] == pulse_methods.ALTERNATING_24:
            for section, keys in (("acquisition", ("depth_cm", "win_words", "tgc_min",
                                                    "tgc_max", "tgc_reach_pct")),
                                  ("transmit", ("n_elem", "single_elem")),
                                  ("receive", ("avg_sweeps",))):
                for key in keys:
                    baseline[section][key] = self.method_base[section][key]
        settings = pulse_methods.profile_settings(current if index == pulse_methods.FAST17 else baseline, index)
        armed = g["pulser"].arm
        self.cb_arm.setChecked(False)
        self.debug_apply(settings)
        self.debug_tick()
        self.method_combo.setCurrentIndex(index)
        if index == pulse_methods.CUSTOM:
            self.method_base = None
        if armed:
            self.cb_arm.setChecked(True)

    def select_method(self, index):
        try:
            self.apply_method(index)
        except Exception as exc:
            self.debug_label.setText(f"Method change failed: {exc}")
            self.method_combo.setCurrentIndex(self.method_index())

    def method_index(self):
        p = self.g["pulser"]
        if p.shot_method == pulse_methods.ALTERNATING_24:
            return pulse_methods.FAST17
        if p.shot_method == 3:
            return pulse_methods.MULTI_RX
        if p.shot_method == 1:
            return pulse_methods.GOLAY
        if p.shot_method == 2:
            return pulse_methods.NEIGHBOR
        if p.chirp_on and (p.chirp_f0_mhz, p.chirp_f1_mhz, p.chirp_us) == (2, 6, 3):
            return pulse_methods.CHIRP
        if not p.chirp_on and (p.t_drive_ns, p.t_dead_ns) == (80, 50) and p.n_cycles in (1, 2):
            return p.n_cycles
        return pulse_methods.CUSTOM

    def debug_fast12(self):
        """Explicit, disarmed candidate; verify new FPGA interlock before timing changes."""
        if self.g['state']['frozen'] or self.debug_jobs:
            QMessageBox.information(self, '12 cm fast',
                'Choose new live run and finish file operations first. Recorded RF keeps its acquisition timing.')
            return
        from acquisition_timing import fast12_settings, timing_budget
        from bench_transport import query_firmware
        import sys
        g=self.g
        g['pulser'].set_arm(False)
        with QSignalBlocker(self.cb_arm):self.cb_arm.setChecked(False)
        try:
            if g['HW']:
                # A live nonce query accepts any build only for capability
                # discovery. The autonomous bench still pins its exact build ID.
                info=query_firmware(sys.modules[g['__name__']])
                if not info['capture_ready_interlock']:
                    raise RuntimeError('Program the capture-ready FPGA build first. The older firmware can skip elements at short gaps.')
            else:
                info={'source':'simulation','capture_ready_interlock':False}
            self.debug_firmware_info=dict(info,checked_utc=datetime.now(timezone.utc).isoformat(),
                note='Capability query before applying fast timing, not current configuration readback.')
            s=fast12_settings(g['settings_snapshot'](self))
            self.debug_apply(s)
            self.debug_tick()
            budget=timing_budget(s,g['pulser'],g['cfg']['win_words'])
            self.debug_label.setText(f"12 cm: nominal {budget['fps_ceiling_nominal']:.1f} fps; PULSER RUN off. Bench validation required.")
        except Exception as exc:
            QMessageBox.warning(self,'Fast timing not applied',str(exc))
        finally:
            g['pulser'].set_arm(False)
            if g['HW']:g['send_cmd'](g['cmd'](0x1e,0),'fast12_lease_release')
            self.pls_refresh()

    def debug_command(self, word, name):
        opcode = (word >> 24) & 255
        self.debug_events.append({"host_monotonic_s": time.perf_counter(),
                                  "name": name, "word_hex": f"{word:08x}"})
        self.debug_events = self.debug_events[-2048:]
        changes_run = opcode in {7, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 22,
                                 23, 24, 25, 27, 28, 29, 32, 33} or (opcode == 16 and word & 1)
        if changes_run and not self.debug_loading:
            self.debug_dirty = True
            self.g["debug_discard_words"] = -1  # UI must finish updating the settings first

    def debug_tick(self):
        if not hasattr(self, "g"):
            return
        while self.debug_results:
            ok, message = self.debug_results.pop(0)
            self.debug_label.setText(message)
            if not ok:
                QMessageBox.warning(self, "Debug operation failed", message)
        self.debug_jobs = [job for job in self.debug_jobs if job.is_alive()]
        if self.debug_offline or self.debug_loading:
            return
        snapshot = self.g["settings_snapshot"](self)
        key = files.acquisition_key(snapshot)
        if self.debug_dirty or key != self.debug_key:
            self.debug_key = key
            self.debug_dirty = False
            self.debug_run_id += 1
            self.debug_epoch = copy.deepcopy(snapshot)
            self.debug_epoch["transmit"]["armed"] = self.g["pulser"].arm
            self.g["recorded_tx_reference"] = None
            with self.g["pipeline_lock"], self.g["buf_lk"]:
                self.debug_reset_buffers()
                # Conservative bounded drain: all eight queued 1 MiB transfers,
                # plus 256 KiB covering device/FPGA buffers. This is NOT an FPGA
                # acknowledgement or a hardware timestamp; document that limit.
                self.g["debug_discard_words"] = (self.g["XFER"]*self.g["NBUF"]//4 + 65536
                                                 if self.g["HW"] else 0)
            self.debug_label.setText(f"Run {self.debug_run_id}: settling queued data")
        elif self.g["debug_discard_words"] == 0 and not self.g["state"]["frozen"]:
            n, secs, _ = self.g["cine"].status()
            self.debug_label.setText(f"Run {self.debug_run_id}: {n} RF sweeps / {secs:.1f}s")

    def debug_reset_buffers(self):
        g = self.g
        g["golay_pairs"].pending = None
        g["three_rx_groups"].reset()
        samples = g["cfg"]["samps"] * pulse_methods.windows_per_tx(g["pulser"].shot_method)
        g["raw_buf"] = np.zeros((48, samples), np.int16)
        g["live_buf"] = np.zeros_like(g["raw_buf"])
        g["carry"] = np.empty(0, np.uint32)
        g["_prev_elem"] = -1
        g["_sweep_seen"].fill(False)
        g["_sweep_bad"].fill(False)
        g["_sweep_fcnt"].fill(-1)
        g["_sweep_ok"] = True
        g["_rej_run"] = 0
        g["stats"]["last_fcnt"] = None
        g["stats"]["dirty"] = False
        with g["replay_lk"]:
            g["replay"]["rf"] = None
        g["cine"].reset()
        g["rf_avg"].reset()
        self.clear_bg()
        g["mm_reset"]()

    def debug_lock_acquisition(self, locked):
        labels = ("depth", "pulse→rx", "damp", "TGC min", "TGC max", "TGC full @", "pulses",
                  "width ns", "dead ns", "settle us", "inhibit us", "ring us",
                  "elements", "element", "chirp f0 M", "chirp f1 M", "chirp us")
        method = self.g["pulser"].shot_method
        sparse = method == pulse_methods.ALTERNATING_24
        self.s_avg.setEnabled(not sparse)
        fixed = set()
        if sparse:
            fixed.update(("depth", "elements", "element"))
        if method in (1, 2, 3):
            fixed.update(("pulses", "chirp f0 M", "chirp f1 M", "chirp us"))
        if method in (2, 3):
            fixed.update(("pulse→rx", "width ns", "dead ns", "settle us", "inhibit us"))
        for label in labels:
            item = self.g["DEBUG_SLIDERS"].get(label)
            if item:
                item[0].setEnabled(not locked and label not in fixed)
        for name in ("cb_signed", "cb_chirp", "cb_single"):
            getattr(self, name).setEnabled(not locked and (name != "cb_chirp" or method == 0 or sparse)
                                           and (name != "cb_single" or not sparse))
        self.method_combo.setEnabled(not locked)
        self.debug_trim_button.setEnabled(not locked and method not in (2, 3))
        self.cb_arm.setEnabled(self.method_verified and not self.debug_offline
                               and (not locked or self.g["pulser"].arm))

    def debug_after_freeze(self):
        if not hasattr(self, "g"):
            return
        with self.g["cine"].lk:
            self.debug_review_quality = copy.deepcopy(list(self.g["cine"].quality))
        self.debug_lock_acquisition(self.g["state"]["frozen"])

    def debug_set_mode(self, index):
        self.g["state"]["debug_view"] = index
        self._refresh_rx()
        self.scene.gl.update()

    def debug_toggle_trim(self):
        if self.g["pulser"].arm:
            self.cb_arm.setChecked(False)
        if self.debug_trim_button.text() == "use flat trim":
            self.debug_saved_trim = list(self.g["pulser"].trim_ns)
            self.g["pulser"].clear_trim()
            self.g["pulser"].trim_note = "Flat trim selected for debugging"
            self.debug_trim_button.setText("restore loaded trim")
        else:
            self.g["pulser"].upload_trim_ns(self.debug_saved_trim)
            self.g["pulser"].trim_note = "Restored in-memory trim table"
            self.debug_trim_button.setText("use flat trim")
        self.debug_dirty = True
        self.debug_tick()

    def debug_apply(self, supplied, replay=False):
        g = self.g
        current = g["settings_snapshot"](self)
        settings = files.validate_settings(supplied, current)
        if not replay and (settings["receive"].get("bg_subtract") or
                           settings["receive"].get("dejitter_on")):
            settings["receive"]["bg_subtract"] = False
            settings["receive"]["dejitter_on"] = False
            self.debug_label.setText("Settings loaded; capture a new background to enable subtraction/de-jitter")
        a, tx, rx, bf, disp = [settings[k] for k in
                              ("acquisition", "transmit", "receive", "beamformer", "display")]
        if not replay and tx.get("shot_method") == 2:
            if tx["chirp_on"] or tx["n_cycles"] != 1 or a["dly_us"] < pulse_methods.neighbor_delay_us(tx):
                raise ValueError("Neighbor receive needs a single-cycle burst and time for the receive switch to settle")
        if not replay and tx.get("shot_method") == 3:
            waveform = (tx["chirp_on"], tx["chirp_f0_mhz"], tx["chirp_f1_mhz"], tx["chirp_us"], tx["t_dead_ns"])
            if waveform != (True, 2., 6., 3., 50.) or a["dly_us"] < pulse_methods.neighbor_delay_us(tx):
                raise ValueError("Three-position RX requires the broad chirp and a settled receive switch")
        if not replay and self.method_base is None and (self.method_index() == pulse_methods.CUSTOM
                or (tx.get("shot_method") == pulse_methods.ALTERNATING_24
                    and self.method_index() != pulse_methods.FAST17)):
            self.method_base = current
        # Complete validation happens above, before any state/hardware mutation.
        self.debug_loading = True
        g["debug_discard_words"] = -1
        try:
            if g["HW"]:
                g["send_cmd"](g["cmd"](0x10, 0), "debug_disarm")
            with g["pipeline_lock"]:
                self._stop_play()
                g["pulser"].arm = False
                g["pulser"].shot_method = tx.get("shot_method", 0)
                g["set_cfg"](a["win_words"])
                g["state"].update(depth_cm=a["depth_cm"], dly_us=a["dly_us"],
                    c=bf["c_m_s"], apod=bf["apod"], cf=bf["cf"], accept=bf["accept_deg"],
                    t0_ns=bf["t0_ns"], dyn=disp["dyn_db"], gain=disp["gain_db"],
                    curve=disp["curve"], auto=disp["auto_gain"],
                    debug_view=disp.get("debug_view", 0),
                    band_on=rx["bandpass_on"], band_f0=rx["band_f0_mhz"],
                    band_bw=rx["band_bw_mhz"], freq_comp=rx.get("frequency_compounding", False),
                    mf=rx["matched_filter"], jit=rx["dejitter_on"])
                g["mode"]["signed"] = disp["signed"]
                g["flip"]["on"] = bf["flip_lr"]
                g["geom"].update(R_mm=bf["R_mm"], pitch_mm=bf["pitch_mm"])
                g["rebuild_geometry"]()
                g["set_dead"](",".join(map(str, bf["dead"])))
                g["rf_avg"].set_n(rx["avg_sweeps"])
                self.gap, self.tgc_lo, self.tgc_hi = a["damp_gap_us"], a["tgc_min"], a["tgc_max"]
                self.tgc_reach_pct = a.get("tgc_reach_pct", 100.)
                for key in files.FIELDS["transmit"]:
                    setattr(g["pulser"], key, tx[key])
                for key in ("chirp_on", "single_elem", "trim_ns"):
                    if key in tx:
                        setattr(g["pulser"], key, copy.deepcopy(tx[key]))
                g["pulser"].trim_note = "Restored settings trim table"
                g["pulser"].t_rx_us = g["pulser_rx_us"](a["dly_us"], a["damp_gap_us"])
                g["pulser"].tx_gen += 1
                if not replay:
                    g["apply_afe_profile"](settings.get("afe"))
                    g["send_seq_config"](self.tgc_lo, self.tgc_hi, a["dly_us"], self.gap,
                                         self.tgc_reach_pct)
                    g["pulser"].push_all()
                with g["buf_lk"]:
                    self.debug_reset_buffers()
                g["view"].update(zoom=disp.get("zoom", 1), cx=disp.get("pan_cx", 0),
                                 cz=disp.get("pan_cz", a["depth_cm"]/200))
                g["bg"]["on"] = rx["bg_subtract"] if replay else False
                self.debug_sync_controls(settings)
        finally:
            self.debug_loading = False
        self.method_combo.setCurrentIndex(self.method_index())
        if not replay and self.method_index() == pulse_methods.CUSTOM:
            self.method_base = None
        self.method_verified = replay or not g["HW"] or not g["pulser"].shot_method
        self.debug_lock_acquisition(self.debug_offline or g["state"]["frozen"])
        if not replay and g["HW"] and g["pulser"].shot_method:
            from bench_transport import check_configuration, query_firmware
            # The identity probe replaces stream callbacks; use the live module, not a copy.
            import sys
            actual = query_firmware(sys.modules[g["__name__"]], with_lease=False)
            if not actual["pulse_methods"] or actual["shot_method"] != pulse_methods.fpga_method(g["pulser"].shot_method):
                raise ValueError("FPGA did not acknowledge the selected acquisition method")
            if g["pulser"].shot_method == 3 and not actual.get("multi_rx"):
                raise ValueError("FPGA does not support tagged three-position receive")
            check_configuration(sys.modules[g["__name__"]], self, actual)
            self.debug_firmware_info = dict(actual,
                checked_utc=datetime.now(timezone.utc).isoformat(),
                note="Disarmed configuration readback after applying acquisition settings.")
            self.method_verified = True
            self.debug_lock_acquisition(g["state"]["frozen"])
        self.t_draw.setInterval(8 if g["pulser"].shot_method == pulse_methods.ALTERNATING_24 else 16)
        self.pls_refresh()
        self.debug_dirty = not replay
        self.scene.gl.update()

    def debug_sync_controls(self, settings):
        a, tx, rx, bf, disp = [settings[k] for k in
                              ("acquisition", "transmit", "receive", "beamformer", "display")]
        values = {"depth": a["depth_cm"], "pulse→rx": a["dly_us"], "damp": a["damp_gap_us"],
                  "TGC min": a["tgc_min"], "TGC max": a["tgc_max"],
                  "TGC full @": a.get("tgc_reach_pct", 100.),
                  "c": bf["c_m_s"], "apod": 100*bf["apod"], "coh": 100*bf["cf"],
                  "aperture": bf["accept_deg"], "R": bf["R_mm"], "pitch": bf["pitch_mm"],
                  "t0": bf["t0_ns"], "dyn range": disp["dyn_db"], "gain": disp["gain_db"],
                  "curve": 100*disp["curve"], "band f0": rx["band_f0_mhz"],
                  "width": rx["band_bw_mhz"], "avg": rx["avg_sweeps"],
                  "pulses": tx["n_cycles"], "width ns": tx["t_drive_ns"],
                  "dead ns": tx["t_dead_ns"], "settle us": tx["t_settle_us"],
                  "inhibit us": tx["t_inhib_us"], "ring us": tx["t_ring_us"],
                  "elements": tx["n_elem"], "element": tx.get("single_elem") or 0,
                  "chirp f0 M": tx["chirp_f0_mhz"], "chirp f1 M": tx["chirp_f1_mhz"],
                  "chirp us": tx["chirp_us"]}
        for label, value in values.items():
            binding = self.g["DEBUG_SLIDERS"].get(label)
            if binding:
                binding[1](value)
        checks = {"cb_signed": disp["signed"], "cb_flip": bf["flip_lr"],
                  "cb_auto": disp["auto_gain"], "cb_band": rx["bandpass_on"],
                  "cb_freq": rx.get("frequency_compounding", False), "cb_mf": rx["matched_filter"],
                  "cb_jit": rx["dejitter_on"], "cb_bg": self.g["bg"]["on"],
                  "cb_arm": False, "cb_chirp": tx["chirp_on"],
                  "cb_single": tx.get("single_elem") is not None}
        for name, value in checks.items():
            widget = getattr(self, name)
            with QSignalBlocker(widget):
                widget.setChecked(value)
        self.elem_v = tx.get("single_elem") or 0
        self.ed_dead.setText(",".join(map(str, bf["dead"])))
        with QSignalBlocker(self.debug_mode):
            self.debug_mode.setCurrentIndex(disp.get("debug_view", 0))

    def debug_load_settings(self):
        if self.g["state"]["frozen"]:
            QMessageBox.information(self, "Load settings", "Choose new live run before loading acquisition settings. Recorded RF keeps its original acquisition settings.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load settings", self.g["SETTINGS_DIR"], "Settings (*.json)")
        if not path:
            return
        try:
            settings = files.load_settings(path, self.g["settings_snapshot"](self))
            self.debug_apply(settings)
            self.debug_tick()
            self.debug_label.setText("Settings restored; PULSER RUN is off")
        except Exception as exc:
            QMessageBox.warning(self, "Settings not loaded", str(exc))

    def debug_new_live(self):
        if self.debug_jobs:
            QMessageBox.information(self, "Operation running", "Wait for the file operation to finish before starting a new run.")
            return
        settings = self.debug_live_settings or self.g["settings_snapshot"](self)
        self.debug_offline = False
        self.setWindowTitle(self.debug_live_title)
        self.g["debug_replay_only"] = False
        self.g["recorded_tx_reference"] = None
        self.debug_apply(settings)
        self.debug_live_settings = None
        self.b_freeze.setChecked(False)
        self.set_frozen(False)
        self.debug_lock_acquisition(False)
        if self.debug_session:
            # Old frames are no longer used by the replay worker after apply's lock.
            self.debug_session.close()
            self.debug_session = None
        self.debug_tick()
        self.debug_label.setText("New run ready; PULSER RUN is off")

    def debug_background_job(self, work, success):
        def run():
            try:
                work()
                self.debug_results.append((True, success))
            except Exception as exc:
                self.debug_results.append((False, str(exc)))
        job = threading.Thread(target=run, daemon=False)
        self.debug_jobs.append(job)
        job.start()

    def debug_save_rf(self):
        if self.debug_jobs:
            return
        if not self.g["state"]["frozen"]:
            self.b_freeze.setChecked(True)
        if not self.review:
            QMessageBox.information(self, "Save RF", "No completed RF sweep is available yet.")
            return
        self.cb_arm.setChecked(False)
        choices = ["Current frame", "Marked range", "Entire frozen cine"]
        choice, ok = self.g["QInputDialog"].getItem(self, "Save RF", "Frames to save", choices, 0, False)
        if not ok:
            return
        if choice == choices[0]:
            ids = [max(0, self.cur_idx)]
        elif choice == choices[1]:
            lo, hi = self.tl.selection()
            ids = [i for i, t in enumerate(self.rev_t) if lo <= t <= hi]
        else:
            ids = list(range(len(self.review)))
        if not ids:
            QMessageBox.information(self, "Save RF", "The selected range contains no frames.")
            return
        selected_ids = list(ids)
        # Preserve averaging history for the first selected frame as well.
        ids = list(range(max(0, ids[0] - self.g["rf_avg"].n + 1), ids[-1] + 1))
        path, _ = QFileDialog.getSaveFileName(self, "Save RF session", "recording.rf.npz", "RF session (*.rf.npz)")
        if not path:
            return
        frames = [self.review[i][1] for i in ids]
        quality = [copy.deepcopy(self.debug_review_quality[i]) for i in ids]
        times = self.rev_t[ids] - self.rev_t[ids[0]]
        meta = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "acquired_settings": copy.deepcopy(self.debug_epoch),
                "review_settings": self.g["settings_snapshot"](self),
                "context": {"note": self.debug_note.text(), "setup": copy.deepcopy(
                    self.debug_session.metadata.get("context", {}).get("setup", {})
                    if self.debug_session else self.debug_setup)},
                "provenance": self.debug_source,
                "command_log": copy.deepcopy(self.debug_events),
                "configuration_boundary": "Host command epoch; queued USB/device data drained conservatively. No firmware configuration readback.",
                "original_frame_indices": ids, "selected_original_frame_indices": selected_ids,
                "initial_review_index": ids.index(selected_ids[0])}
        if self.debug_session:
            meta["parent_recording"] = copy.deepcopy(self.debug_session.metadata)
        reference = self.g["mf_reference"]().copy()
        bg = self.g["bg"]["ref"]
        bg = None if bg is None else bg.copy()
        self.debug_label.setText(f"Saving {len(ids)} RF frames…")
        def work():
            files.save_session(path, frames, times, meta, quality, reference, bg)
            report = files.diagnostics(frames, quality,
                                       shot_method=meta["acquired_settings"]["transmit"].get("shot_method", 0))
            files.atomic_json(Path(path).with_suffix(".report.json"), report)
        self.debug_background_job(work, f"Saved RF + report: {Path(path).name}")

    def debug_open_rf(self, path=None, raise_errors=False):
        if self.debug_jobs:
            return
        if not isinstance(path, (str, Path)):
            path, _ = QFileDialog.getOpenFileName(self, "Open RF session", "", "RF session (*.rf.npz)")
        if not path:
            return
        loaded = None
        try:
            loaded = files.load_session(path)  # validate everything before changing the live state
            acquired = loaded.metadata["acquired_settings"]
            review = copy.deepcopy(loaded.metadata.get("review_settings", acquired))
            review["acquisition"] = copy.deepcopy(acquired["acquisition"])
            review["transmit"] = copy.deepcopy(acquired["transmit"])
            review = files.validate_settings(review, self.g["settings_snapshot"](self))
            initial = loaded.metadata.get("initial_review_index", 0)
            if type(initial) is not int or not 0 <= initial < len(loaded.rf):
                raise ValueError("Invalid initial review frame")
            if self.debug_live_settings is None:
                self.debug_live_settings = self.g["settings_snapshot"](self)
            self.cb_arm.setChecked(False)
            self.debug_offline = True
            self.g["debug_replay_only"] = True
            self.debug_apply(review, replay=True)
            old = self.debug_session
            self.debug_session = loaded
            self.debug_epoch = copy.deepcopy(acquired)
            self.g["recorded_tx_reference"] = loaded.tx_reference.copy()
            self.g["_mf_ref"]["gen"] = None
            self.g["_hilb"]["key"] = None
            self.pls_refresh()
            self.g["bg"]["ref"] = loaded.background
            if loaded.background is None:
                self.g["bg"]["on"] = False
                self.g["state"]["jit"] = False
                self.cb_bg.setChecked(False)
                self.cb_jit.setChecked(False)
            self.g["cine"].recording = False
            self.g["state"]["frozen"] = True
            with QSignalBlocker(self.b_freeze):
                self.b_freeze.setChecked(True)
            self.b_freeze.setText("FILE REPLAY")
            self.review = list(zip(loaded.timestamps, loaded.rf))
            self.rev_t = loaded.timestamps - loaded.timestamps[0]
            self.debug_review_quality = loaded.quality
            self.cur_idx = -1
            self._cine_enable(True)
            self.debug_lock_acquisition(True)
            self.debug_note.setText(str(loaded.metadata.get("context", {}).get("note", "")))
            self.tl.t_in = self.tl.t_out = None
            self._seek(float(self.rev_t[initial]), force=True)
            degraded = sum(not q["valid"] for q in loaded.quality)
            self.debug_label.setText(f"File: {len(self.review)} frames / {degraded} degraded")
            self.setWindowTitle(f"TFM B-mode — FILE REPLAY: {Path(path).name}")
            if old:
                old.close()
        except Exception as exc:
            if loaded is not None and loaded is not self.debug_session:
                loaded.close()
            if raise_errors:
                raise
            QMessageBox.warning(self, "RF not loaded", str(exc))

    def debug_report(self):
        if not self.g["state"]["frozen"]:
            self.b_freeze.setChecked(True)
        if not self.review or self.debug_jobs:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save RF diagnostics", "rf-report.json", "JSON (*.json)")
        if not path:
            return
        frames = [item[1] for item in self.review]
        quality = copy.deepcopy(self.debug_review_quality)
        settings = copy.deepcopy(self.debug_epoch)
        context = self.debug_note.text()
        def work():
            report = files.diagnostics(frames, quality)
            report.update(acquired_settings=settings, context=context, provenance=self.debug_source)
            files.atomic_json(path, report)
        self.debug_background_job(work, f"Saved report: {Path(path).name}")
