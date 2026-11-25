"""Shot tagging and pulse/acquisition profiles for the TFM viewer."""
from __future__ import annotations
import copy
import math
import numpy as np

CUSTOM, ONE, TWO, CHIRP, GOLAY, NEIGHBOR, MULTI_RX, FAST17 = range(8)
PROFILES = ("Current / custom", "One-cycle burst", "Two-cycle burst",
            "Broad 2-6 MHz chirp", "Golay pair (4 chips)", "Neighbor RX (one cycle)",
            "Three-position RX (broad chirp)", "Fast 17 cm (stable 24)")
GOLAY_CODES = ((1, 1, 1, -1), (1, 1, -1, 1))
RX_OFFSETS = (0, -1, 1)

# Host acquisition method 4 uses ordinary pulse-echo on the FPGA. Live
# acquisition repeats BANK_A: one position from every adjacent pair, spread
# across the full aperture, with the two known-dead positions omitted. BANK_B
# remains the explicit complement for validation and offline aperture tests;
# the live sequencer only walks BANK_A.
ALTERNATING_24 = 4
BANK_A = (1, 3, 4, 7, 9, 11, 12, 14, 17, 19, 20, 22,
          24, 26, 28, 31, 32, 34, 37, 39, 40, 42, 44, 47)
BANKS = (BANK_A, tuple(i for i in range(48) if i not in BANK_A))
BANK_FOR_ELEMENT = np.array([int(i not in BANK_A) for i in range(48)])
SLOT_FOR_ELEMENT = np.argsort(BANKS[0] + BANKS[1])


class BankFrame(np.ndarray):
    """Keep the physical aperture attached to this frame through copies and band slices."""
    def __new__(cls, data, bank):
        obj = np.asarray(data).view(cls)
        if bank not in (0, 1):
            raise ValueError("Sparse frames require a physical aperture group")
        obj.bank = int(bank)
        return obj

    def __array_finalize__(self, parent):
        self.bank = getattr(parent, 'bank', None)


def fpga_method(method):
    return 0 if method == ALTERNATING_24 else method


def windows_per_tx(method):
    return {1: 2, 3: 3}.get(method, 1)


def shots_per_sweep(method, n_elem, single_elem):
    if method == ALTERNATING_24:
        return 24
    elements = (single_elem,) if single_elem is not None else range(n_elem)
    shots = len(elements) * windows_per_tx(method)
    if method == 3:
        shots -= int(0 in elements) + int(47 in elements)
    return shots


def neighbor_delay_us(tx):
    # Trigger precedes the biased trim, burst, HV inhibit and a 64-bit mux shift.
    burst_us = 2 * (tx['t_drive_ns'] + tx['t_dead_ns']) / 1000
    if tx.get('shot_method') == 3:
        # This profile uses a 3 us chirp, with all 24 quantized halves longer
        # than the 50 ns dead interval. The guard covers edge quantization.
        burst_us = 3.
    return math.ceil(2 + max(tx['trim_ns'])/1000 + burst_us + tx['t_inhib_us']
                     + 6.4 + .07 + tx['t_settle_us'] + .2)


def profile_settings(base, profile):
    settings = copy.deepcopy(base)
    if profile == CUSTOM:
        return settings
    tx, acq = settings['transmit'], settings['acquisition']
    if profile == FAST17:
        # Same sizing convention as the live depth slider. Preserve the pulse,
        # receive offset and inter-shot gap; the fixed 24-position walk is one
        # image.  The measured heart RF has near-field headroom but weak deep
        # echoes, so start lower and reach full TGC at 56% of the gate, then hold.
        tx.update(shot_method=ALTERNATING_24, n_elem=48, single_elem=None)
        acq.update(depth_cm=17, win_words=int((2*.17/1496)*40e6)//2,
                   tgc_min=1400, tgc_max=4095, tgc_reach_pct=56.)
        settings['receive']['avg_sweeps'] = 1
        return settings
    chirp = profile in (CHIRP, MULTI_RX)
    tx.update(shot_method={GOLAY: 1, NEIGHBOR: 2, MULTI_RX: 3}.get(profile, 0),
              chirp_on=chirp, n_cycles=2 if profile == TWO else 4 if profile == GOLAY else 1,
              t_drive_ns=80., t_dead_ns=50.)
    if chirp:
        tx.update(chirp_f0_mhz=2., chirp_f1_mhz=6., chirp_us=3.)
    if profile in (NEIGHBOR, MULTI_RX):
        acq['dly_us'] = max(acq['dly_us'], neighbor_delay_us(tx))
    settings['receive']['matched_filter'] = chirp
    return settings


class ThreeRxGroups:
    """Assemble one TX row from consecutive tagged shots, even across USB transfers."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.parts = []
        self.overflow = False

    def unpack(self, kinds, elems, counters, rf, bad):
        ends = (kinds == 2) | ((elems == 47) & (kinds == 1))
        count = int(ends.sum())
        samples = rf.shape[1]
        packed = np.zeros((count, 3, samples), rf.dtype)
        rejected = np.zeros(count, bool)
        out = 0
        for i, (slot, tx, counter) in enumerate(zip(kinds, elems, counters)):
            if self.parts and self.parts[-1][1] != tx:
                self.reset()
            if len(self.parts) < 3:
                self.parts.append((slot, tx, counter, rf[i], bad[i]))
            else:
                self.overflow = True
            if not ends[i]:
                continue
            expected = (0, 2) if tx == 0 else (0, 1) if tx == 47 else (0, 1, 2)
            valid = not self.overflow and len(self.parts) == len(expected)
            for j, (part, want) in enumerate(zip(self.parts, expected)):
                kind, _, fcnt, row, damaged = part
                valid &= kind == want and not damaged and (fcnt - self.parts[0][2]) % 65536 == j
                packed[out, want] = row
            rejected[out] = not valid
            self.reset()
            out += 1
        return elems[ends], counters[ends], packed.reshape(count, 3*samples), rejected


class GolayPairs:
    """Reassemble tagged A/B shots across USB reads, retaining both original RF windows."""
    def __init__(self):
        self.pending = None

    def unpack(self, kinds, elems, counters, rf, bad):
        if self.pending is not None:
            kinds, elems, counters, rf, bad = [np.concatenate((previous, current))
                for previous, current in zip(self.pending, (kinds, elems, counters, rf, bad))]
        self.pending = None
        if kinds[-1] == 1:
            self.pending = tuple(a[-1:].copy() for a in (kinds, elems, counters, rf, bad))
        b = np.flatnonzero(kinds == 2)
        a = np.maximum(b-1, 0)
        valid = ((b > 0) & (kinds[a] == 1) & (elems[a] == elems[b])
                 & (((counters[b]-counters[a]) & 0xffff) == 1))
        first = rf[a].copy()
        first[~valid] = 0
        return elems[b], counters[b], np.concatenate((first,rf[b]), axis=1), bad[b] | bad[a] | ~valid


def decode_golay(packed, chip_samples):
    """Correlate each receive window with its chip signs and add at the first-chip origin."""
    first, second = np.split(np.asarray(packed, np.float32), 2, axis=1)
    out = np.zeros_like(first)
    for i, (a, b) in enumerate(zip(*GOLAY_CODES)):
        offset = i * chip_samples
        lag = int(offset)
        frac = offset - lag
        for shift, weight in ((lag,1-frac), (lag+1,frac)):
            n = first.shape[1] - shift
            if n > 0 and weight:
                out[:,:n] += (weight/8) * (a*first[:,shift:] + b*second[:,shift:])
    return out
