"""AFE5804 receive profile shared by the live host and saved RF metadata.

The probe/multiplexer feeds AFE channel 1.  The remaining seven ADC channels
are unused, so powering them down removes avoidable digital/LVDS activity.
"""
from __future__ import annotations

import copy


RECOMMENDED = {
    "profile": "ch1-low-noise-plus6",
    "pga_db": 30,
    "tgc_mode": "I",
    "lpf_mhz": 12.5,
    "digital_gain_db": 6,
    "lfns_ch1": False,
    "active_channels": [1],
}

_PGA_BITS = {20: 0, 25: 1, 27: 2, 30: 3}
_TGC_BITS = {"I": 0x10, "II": 0x20}


def recommended_profile():
    return copy.deepcopy(RECOMMENDED)


def register_writes(profile=None):
    """Return absolute ``(address, value)`` writes for an AFE5804 profile."""
    p = RECOMMENDED if profile is None else profile
    pga = int(p["pga_db"])
    mode = str(p["tgc_mode"]).upper()
    lpf = float(p["lpf_mhz"])
    dgain = int(p["digital_gain_db"])
    active = {int(v) for v in p["active_channels"]}
    if pga not in _PGA_BITS:
        raise ValueError("AFE PGA must be 20, 25, 27, or 30 dB")
    if mode not in _TGC_BITS:
        raise ValueError("AFE TGC mode must be I or II")
    if lpf not in (12.5, 17.0):
        raise ValueError("AFE LPF must be 12.5 or 17 MHz")
    if not 0 <= dgain <= 12:
        raise ValueError("AFE digital gain must be between 0 and 12 dB")
    if not active or not active <= set(range(1, 9)):
        raise ValueError("AFE active_channels must contain channel IDs 1 through 8")

    # 0x16: D1:D0 must be one; D3 selects the 12.5 MHz LPF; D5:D4
    # select TGC mode; D7:D6 select PGA gain.
    vca = 0x0003 | (_PGA_BITS[pga] << 6) | _TGC_BITS[mode]
    if lpf == 12.5:
        vca |= 0x0008
    # Register 0x0F is not numbered linearly: D3:D0 are PDN_CH<1:4>
    # (CH1 at D3 through CH4 at D0), while D7:D4 are PDN_CH<8:5>
    # (CH8 at D7 through CH5 at D4).  CH1-only is therefore 0x00F7.
    def pd_bit(ch):
        return 4 - ch if ch <= 4 else ch - 1
    power_down = sum(1 << pd_bit(ch) for ch in range(1, 9) if ch not in active)
    return [
        (0x16, vca),
        (0x0F, power_down),
        (0x14, 0x0001 if p.get("lfns_ch1", False) else 0x0000),
        (0x2A, dgain),
    ]


def metadata(profile=None):
    result = copy.deepcopy(RECOMMENDED if profile is None else profile)
    result["requested_registers"] = {
        f"0x{addr:02X}": f"0x{value:04X}" for addr, value in register_writes(result)
    }
    result["readback"] = "unavailable; absolute writes are reapplied by the host"
    return result
