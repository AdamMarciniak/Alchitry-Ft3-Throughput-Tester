"""Pure planning helpers: no hardware imports or transmit commands."""
import copy
from rf_debug import validate_settings


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
    a['tgc_max']=a['tgc_min']+round((a['tgc_max']-a['tgc_min'])*min(1.,words/old_words))
    a.update(depth_cm=12.,win_words=words,damp_gap_us=50.)
    s['transmit'].update(armed=False,n_elem=48,single_elem=None)
    s['receive']['avg_sweeps']=1
    s['display'].update(pan_cx=0.,pan_cz=None,zoom=1.)
    return s


def timing_budget(settings, pulser, words):
    """Nominal timing only: FIFO stalls, sample-grid alignment and trims add time."""
    a=settings['acquisition']
    n=1 if pulser.single_elem is not None else pulser.n_elem
    period=pulser.element_period_us()
    frame_us=n*period
    return {'receive_window_us':2*words/40.,'post_receive_gap_us':a['damp_gap_us'],
            'element_period_us':period,'aperture_ms_nominal':frame_us/1000,
            'fps_ceiling_nominal':1e6/frame_us,
            'rf_link_MB_s_nominal':n*(words+1)*4/(frame_us),
            'note':'Nominal requested timing, not measured FPS; stalls, grid alignment and element trims add time.'}
