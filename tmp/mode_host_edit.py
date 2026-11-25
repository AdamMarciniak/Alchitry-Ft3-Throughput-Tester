from pathlib import Path
p=Path('host/pulser_ctrl.py');s=p.read_text().replace('        self.single_elem = None','        self.shot_method = 0\n        self.single_elem = None',1)
s=s.replace('if self.chirp_on:\n            return', 'if self.chirp_on and self.shot_method != 1:\n            return')
s=s.replace('return self.n_cycles * 2.0','return (4 if self.shot_method == 1 else self.n_cycles) * 2.0').replace('return n * self.element_period_us()', 'return (2 if self.shot_method == 1 else 1) * n * self.element_period_us()')
s=s.replace('    def tx_waveform(self, fs_hz):','    def tx_waveform(self, fs_hz, member_b=False):').replace('if self.chirp_on:\n            edges =', 'if self.chirp_on and self.shot_method != 1:\n            edges =').replace('range(2 * self.n_cycles):','range(2 * (4 if self.shot_method == 1 else self.n_cycles)):').replace('            for i in range(i0,','            if self.shot_method == 1 and m//2 == (2 if member_b else 3):\n                s = -s\n            for i in range(i0,')
s=s.replace('        self.set_n_cycles(self.n_cycles)','        self._send(self._cmd(0x20, self.shot_method), "pls_method")\n        self.set_n_cycles(self.n_cycles)',1)
p.write_text(s)
p=Path('host/tfm_gl_host.py');s=p.read_text().replace('import rf_debug\n','import rf_debug\nfrom pulse_methods import GolayPairs, decode_golay\n')
s=s.replace('    return m\n','    return m\n',1).replace('        m[sorted(d)] = 0.0','        m[sorted(d)] = 0.0\n        if ctl is not None and ctl.shot_method == 2:\n            m[[i ^ 1 for i in d]] = 0.0')
s=s.replace('raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  #','golay_pairs = GolayPairs()\nraw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  #',1)
s=s.replace('    keep = elems < N_ELEM','''    if pulser.shot_method == 1:
        elems, fcnt, c, bad_rows = golay_pairs.unpack((hdr >> 22) & 3, elems, fcnt, c, bad_rows)
        if not elems.size:
            return
    keep = elems < N_ELEM''')
s=s.replace('        complete = _sweep_ok', '        complete = _sweep_ok').replace('if _rej_run >= REJECT_MAX:', 'if _rej_run >= REJECT_MAX and pulser.shot_method != 1:')
s=s.replace('def process(words):','''def valid_headers(words):
    kind = (words >> 22) & 3
    if pulser.shot_method == 1:
        valid = (kind == 1) | (kind == 2)
    else:
        valid = kind == (3 if pulser.shot_method == 2 else 0)
    return ((words >> 24) == 0xe1) & valid & (((words >> 16) & ELEM_MASK) < N_ELEM)


def process(words):''').replace('(hdrs >> HDR_SHIFT) == HDR_MAGIC','valid_headers(hdrs)').replace('(w[pos+1:] >> HDR_SHIFT) == HDR_MAGIC','valid_headers(w[pos+1:])')
s=s.replace('samps = rf.shape[1]','samps = cfg["samps"]').replace('samps = rep.shape[1]','samps = cfg["samps"]')
s=s.replace('        cond, sh = _condition(','''        if rf.shape[1] == 2 * samps and pulser.shot_method == 1:
            rf = decode_golay(rf, golay_chip_samples())
        elif rf.shape[1] != samps:
            raise ValueError("RF window length does not match the acquisition method")
        cond, sh = _condition(''')
s=s.replace('def prepare_analytic(','''def golay_chip_samples():
    return 2 * (pls_ns_to_cyc(pulser.t_drive_ns) + pls_ns_to_cyc(pulser.t_dead_ns)) * FS_HZ / CLK_HZ


def prepare_analytic(''')
s=s.replace('    ref  = mf_reference() if mf else None','    ref  = mf_reference() if mf else None\n    if mf and pulser.shot_method == 1:\n        ref = ref[:max(1, round(golay_chip_samples()))]')
s=s.replace('    t    = (2.0 * d / state["c"]', '''    paths = 2.0*d
    if pulser.shot_method == 2:
        paths = d + d[:, np.arange(N_ELEM)^1]
    t    = (paths / state["c"]''')
s=s.replace('    cacc = float(np.cos(np.radians(state["accept"])))','    if pulser.shot_method == 2:\n        cosa = np.minimum(cosa, cosa[:, np.arange(N_ELEM)^1])\n    cacc = float(np.cos(np.radians(state["accept"])))',1)
s=s.replace('uniform float alive[','uniform int neighbor_rx;\nuniform float alive[')
s=s.replace('float t = (2.0 * d / c + t0_s - dly_s) * fs;', '''float path = 2.0 * d;
        vec2 rv = p - elems[i ^ 1].xy;
        if (neighbor_rx != 0) path = d + length(rv);
        float t = (path / c + t0_s - dly_s) * fs;''')
s=s.replace('        if (t >= 0.0 && t <= samps', '        if (neighbor_rx != 0) cosa = min(cosa, dot(rv, elems[i ^ 1].zw) / max(length(rv), 1e-9));\n        if (t >= 0.0 && t <= samps')
s=s.replace("        p['cf_pow'].value", "        p['neighbor_rx'].value = int(pulser.shot_method == 2)\n        p['cf_pow'].value")
s=s.replace('dead["gen"], pulser.n_elem, pulser.single_elem','dead["gen"], pulser.n_elem, pulser.single_elem, pulser.shot_method')
s=s.replace('            "armed":         pulser.arm,','            "armed":         pulser.arm,\n            "shot_method":   pulser.shot_method,')
s=s.replace('            raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)','            golay_pairs.pending = None\n            raw_buf = np.zeros((N_ELEM, cfg["samps"]*(2 if pulser.shot_method == 1 else 1)), dtype=np.int16)')
s=s.replace('            if cfg["samps"] == samps:', '            if cfg["samps"] == samps and raw_buf.shape == a.shape:')
p.write_text(s)
p=Path('host/bench_render.py');s=p.read_text().replace("'cf_pow': h.state['cf']", "'neighbor_rx': int(h.pulser.shot_method == 2), 'cf_pow': h.state['cf']");p.write_text(s)
p=Path('host/rf_debug.py');s=p.read_text().replace('    tx = document.get("transmit", {})','''    tx = document.get("transmit", {})
    # Complete legacy snapshots predate method tags and always use pulse-echo.
    if "shot_method" in tx or "n_cycles" in tx and "trim_ns" in tx:
        result["transmit"]["shot_method"] = _number(tx.get("shot_method", 0), "shot_method", 0, 2, True)''').replace('"chirp_on", "single_elem", "trim_ns")','"chirp_on", "single_elem", "trim_ns", "shot_method")')
s=s.replace('<= 131070','<= 262140').replace('meta["acquired_settings"]["acquisition"]["win_words"] * 2 != shape[1]','recorded_samples(meta["acquired_settings"]) != shape[1]').replace('2 * meta["acquired_settings"]["acquisition"]["win_words"]','recorded_samples(meta["acquired_settings"])')
s=s.replace('def save_session(','''def recorded_samples(settings):
    return settings["acquisition"]["win_words"] * (4 if settings["transmit"].get("shot_method") == 1 else 2)


def save_session(''').replace('background.shape != rf.shape[1:]', 'background.shape != (48, meta["acquired_settings"]["acquisition"]["win_words"]*2)')
p.write_text(s)
p=Path('host/bench_transport.py');s=p.read_text().replace("'capture_ready_interlock':", "'pulse_methods': bool(p[3]&8), 'shot_method': (p[3]>>4)&3,\n                'capture_ready_interlock':").replace('expected_build_id=None, timeout=4):','expected_build_id=None, timeout=4, with_lease=True):').replace("        h.send_cmd(h.cmd(0x1e, 2000), 'bench_lease_renew')\n        h.debug_probe_consumer", "        if with_lease:\n            h.send_cmd(h.cmd(0x1e, 2000), 'bench_lease_renew')\n        h.debug_probe_consumer").replace("or not result['lease_enabled'] or result['lease_remaining_ms'] <= 0:", "or (with_lease and not (result['lease_enabled'] and result['lease_remaining_ms'] > 0)):").replace('if time.monotonic()-renewed > .25:', 'if with_lease and time.monotonic()-renewed > .25:')
p.write_text(s)
