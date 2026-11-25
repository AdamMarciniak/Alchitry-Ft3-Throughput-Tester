from pathlib import Path
p=Path('host/rf_debug_ui.py');s=p.read_text().replace('import rf_debug as files','import rf_debug as files\nimport pulse_methods')
s=s.replace('        self.debug_mode = QComboBox()', '''        self.method_base = None
        self.method_combo = QComboBox()
        self.method_combo.setAccessibleName("Acquisition and pulse method")
        self.method_combo.addItems(pulse_methods.PROFILES)
        self.method_combo.setToolTip("Choose the firing and receive sequence. A live switch starts a new RF epoch.")
        self.method_combo.activated.connect(self.select_method)
        layout.addWidget(self.method_combo)
        self.debug_mode = QComboBox()''')
s=s.replace('    def debug_fast12(self):','''    def apply_method(self, index):
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
        settings = pulse_methods.profile_settings(baseline, index)
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
        if p.shot_method == 1:
            return pulse_methods.GOLAY
        if p.shot_method == 2:
            return pulse_methods.NEIGHBOR
        if p.chirp_on and (p.chirp_f0_mhz, p.chirp_f1_mhz, p.chirp_us) == (2, 6, 3):
            return pulse_methods.CHIRP
        if not p.chirp_on and (p.t_drive_ns, p.t_dead_ns) == (80, 50) and p.n_cycles in (1, 2):
            return p.n_cycles
        return pulse_methods.CUSTOM

    def debug_fast12(self):''')
s=s.replace('        samples = g["cfg"]["samps"]','        g["golay_pairs"].pending = None\n        samples = g["cfg"]["samps"] * (2 if g["pulser"].shot_method == 1 else 1)')
s=s.replace('        self.debug_trim_button.setEnabled(not locked)','        self.method_combo.setEnabled(not locked)\n        self.debug_trim_button.setEnabled(not locked)')
s=s.replace('                g["pulser"].arm = False','                g["pulser"].arm = False\n                g["pulser"].shot_method = tx.get("shot_method", 0)')
s=s.replace('        self.pls_refresh()\n        self.debug_dirty = not replay','''        self.method_combo.setCurrentIndex(self.method_index())
        if not replay and g["HW"] and g["pulser"].shot_method:
            from types import SimpleNamespace
            from bench_transport import query_firmware
            actual = query_firmware(SimpleNamespace(**g), with_lease=False) if False else None
            # The identity probe replaces stream callbacks; use the live module, not a copy.
            import sys
            actual = query_firmware(sys.modules[g["__name__"]], with_lease=False)
            if not actual["pulse_methods"] or actual["shot_method"] != g["pulser"].shot_method:
                raise ValueError("FPGA did not acknowledge the selected acquisition method")
        self.pls_refresh()
        self.debug_dirty = not replay''').replace('            from types import SimpleNamespace\n','').replace('            actual = query_firmware(SimpleNamespace(**g), with_lease=False) if False else None\n','')
p.write_text(s)
p=Path('host/bench_host.py');s=p.read_text().replace("WAVEFORM_FIELDS = ('chirp_on',","WAVEFORM_FIELDS = ('shot_method', 'chirp_on',");p.write_text(s)
