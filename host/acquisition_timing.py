"""Pure planning helpers: no hardware imports or transmit commands."""
import copy
from rf_debug import validate_settings


def tgc_increment(lo, hi, win_words, reach_pct=100):
    """12.12 DAC-code increment that reaches ``hi`` at the chosen window %.

    Firmware clamps the accumulator at the separately programmed high code,
    so the second segment is a true hold rather than an overshooting ramp.
    """
    words = max(1, int(win_words))
    pct = min(100.0, max(1.0, float(reach_pct)))
    knee_words = max(1, min(words, int(round(words * pct / 100.0))))
    return max(0, (max(int(lo), int(hi)) - int(lo)) * 4096 // knee_words)


def fast12_settings(current):
    """Retain all 48 shots and waveform; shorten capture and post-window gap.

    The host's depth slider uses 1496 m/s to size its window independently of
    display sound speed. Preserve that convention (including receive-offset
    headroom), and preserve the old linear TGC slope when shortening the gate.
    This is a bench-validation candidate, not a verified on-body output level.
    """
    s=validate_settings(copy.deepcopy(current))
    a=s['acquisition']
    words=max(320,int((2*.12/1496)*40e6)//2)
    old_words=a['win_words']
    old_knee=max(1,old_words*a.get('tgc_reach_pct',100)/100)
    a['tgc_max']=min(4095,a['tgc_min']+round((a['tgc_max']-a['tgc_min'])*min(1.,words/old_knee)))
    a.update(depth_cm=12.,win_words=words,damp_gap_us=50.,tgc_reach_pct=100.)
    s['transmit'].update(armed=False,n_elem=48,single_elem=None)
    from pulse_methods import ALTERNATING_24
    if s['transmit'].get('shot_method') == ALTERNATING_24:
        s['transmit']['shot_method'] = 0
    s['receive']['avg_sweeps']=1
    s['display'].update(pan_cx=0.,pan_cz=None,zoom=1.)
    return s


def timing_budget(settings, pulser, words):
    """Nominal timing only: FIFO stalls, sample-grid alignment and trims add time."""
    a=settings['acquisition']
    from pulse_methods import shots_per_sweep
    period=pulser.element_period_us()
    shots=shots_per_sweep(getattr(pulser, 'shot_method', 0), pulser.n_elem, pulser.single_elem)
    frame_us=shots*period
    return {'receive_window_us':2*words/40.,'post_receive_gap_us':a['damp_gap_us'],
            'element_period_us':period,'aperture_ms_nominal':frame_us/1000,
            'fps_ceiling_nominal':1e6/frame_us,
            'rf_link_MB_s_nominal':shots*(words+1)*4/(frame_us),
            'note':'Nominal requested timing, not measured FPS; stalls, grid alignment and element trims add time.'}
