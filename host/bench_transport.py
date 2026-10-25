"""Disarmed FPGA identity/configuration handshake over the existing USB stream."""
import secrets
import threading
import time
import numpy as np

MAGIC = 0xB34D0001


class InfoProbe:
    def __init__(self, nonce, build_id):
        self.nonce, self.build_id = nonce, build_id
        self.event = threading.Event()
        self.tail = np.empty(0, np.uint32)
        self.packet = None

    def feed(self, words):
        a = np.concatenate((self.tail, words))
        hits = np.flatnonzero(a == MAGIC)
        for start in hits[-32:][::-1]:
            if start + 16 > len(a):
                continue
            row = a[start:start+16]
            if (int(row[1]) == self.nonce and
                    (self.build_id is None or int(row[2]) == self.build_id) and int(row[3]) >> 16 == 1):
                self.packet = row.copy()
                self.event.set()
                break
        self.tail = a[-15:].copy()

    def result(self):
        if self.packet is None:
            raise ValueError('No matching firmware identity response')
        p = [int(v) for v in self.packet]
        return {'protocol': 1, 'nonce': self.nonce, 'runtime_build_id': f'{p[2]:08x}',
                'armed': bool(p[3]&1), 'lease_enabled': bool(p[3]&2), 'lease_remaining_ms': p[4],
                'capture_ready_interlock': bool(p[3]&4),
                'win_words': p[5], 'dly_cycles': p[6], 'gap_cycles': p[7],
                'tgc_start': p[8], 'tgc_increment': p[9], 'n_cycles': (p[10]>>16)&255,
                'drive_cycles': p[10]&65535, 'dead_cycles': p[11],
                'settle_cycles': p[12], 'inhibit_cycles': p[13],
                'ring_cycles': p[14], 'rx_cycles': p[15]}


def query_firmware(h, expected_build_id=None, timeout=4):
    probe = InfoProbe(secrets.randbelow(0xffffff)+1,
                      None if expected_build_id is None else int(expected_build_id, 16))
    old = h.debug_replay_only
    h.debug_replay_only = False
    try:
        h.pulser.set_arm(False)
        h.send_cmd(h.cmd(0x1e, 2000), 'bench_lease_renew')
        h.debug_probe_consumer = probe.feed
        h.send_cmd(h.cmd(h.OP_STOP), 'bench_probe_stop')
        h.send_cmd(h.cmd(h.OP_RST_CNT), 'bench_probe_reset_counter')
        h.send_cmd(h.cmd(0x1f, probe.nonce), 'bench_probe_nonce')
        h.send_cmd(h.cmd(0x06, 0), 'bench_probe_unlimited')
        h.send_cmd(h.cmd(h.OP_SET_SRC, 3), 'bench_probe_source')
        h.send_cmd(h.cmd(h.OP_START), 'bench_probe_start')
        deadline = time.monotonic()+timeout
        renewed = time.monotonic()
        while time.monotonic() < deadline and h.stats['alive']:
            if probe.event.wait(.05):
                result = probe.result()
                if result['armed'] or not result['lease_enabled'] or result['lease_remaining_ms'] <= 0:
                    raise RuntimeError('Firmware did not confirm disarmed operation with an active lease')
                return result
            if time.monotonic()-renewed > .25:
                h.send_cmd(h.cmd(0x1e, 2000), 'bench_lease_renew')
                renewed = time.monotonic()
        raise TimeoutError('Running FPGA did not echo this nonce/build ID; reprogram the checked build before acquisition')
    finally:
        h.send_cmd(h.cmd(h.OP_STOP), 'bench_probe_stop')
        h.send_cmd(h.cmd(h.OP_SET_SRC, h.SRC_SEQ), 'bench_probe_restore_sequence')
        h.debug_probe_consumer = None
        h.send_cmd(h.cmd(h.OP_START), 'bench_probe_resume')
        h.debug_replay_only = old


def check_configuration(h, window, info):
    lo, hi = window.tgc_lo, max(window.tgc_lo, window.tgc_hi)
    p = h.pulser
    expected = {'win_words': h.cfg['win_words'], 'dly_cycles': h.us_to_cycles(h.state['dly_us']),
                'gap_cycles': h.us_to_cycles(window.gap), 'tgc_start': lo,
                'tgc_increment': ((hi-lo)*4096)//h.cfg['win_words'],
                'n_cycles': p.n_cycles, 'drive_cycles': h.pls_ns_to_cyc(p.t_drive_ns),
                'dead_cycles': h.pls_ns_to_cyc(p.t_dead_ns),
                'settle_cycles': h.pls_us_to_cyc(p.t_settle_us),
                'inhibit_cycles': h.pls_us_to_cyc(p.t_inhib_us),
                'ring_cycles': h.pls_us_to_cyc(p.t_ring_us),
                'rx_cycles': h.pls_us_to_cyc(p.t_rx_us)}
    mismatch = {k: {'requested': v, 'readback': info.get(k)} for k,v in expected.items() if info.get(k) != v}
    if mismatch:
        raise RuntimeError(f'FPGA configuration readback differs from host requests: {mismatch}')
    return expected
