# tfm_gl_host.py
#   python tfm_gl_host.py            -> live GPU TFM B-mode with calipers
#   python tfm_gl_host.py signed     -> treat samples as 12-bit two's complement
#   python tfm_gl_host.py sim        -> no hardware; synthetic phantom (UI testing)
#   python tfm_gl_host.py flip       -> start with the array mirrored L/R
#                                       (also a checkbox; see ELEM_UNIFORM_FLIP)
#
# Same acquisition path as tfm_host.py (SRC_SEQ: the FPGA fires elements 0..N-1
# in turn and streams back one TGC-ramped receive window per fire, tagged with
# the element id).  The difference is everything downstream of the USB read:
#
#   tfm_host.py            this file
#   -----------            ---------
#   numpy gather, N x      fragment shader, one thread per screen pixel,
#     (NX*NZ) fancy index    N-element loop in registers
#   np.rint nearest-       hardware bilinear sampling of the analytic signal
#     sample delay index     (fractional delays -> visibly less speckle)
#   fixed 320x256 grid     reconstructs at the window's native pixel size
#   PPM string -> tk       texture -> screen, no CPU copy
#   ~15-20 ms/frame        ~0.2-0.5 ms/frame
#
# The only per-frame CPU work left is the Hilbert transform (N FFTs) and the
# texture upload; the delay LUT is gone entirely, so sound speed, aperture and
# zoom are free live uniforms instead of a tens-of-ms rebuild.
#
# Pipeline, all on the GPU:
#   pass 1  beamform    -> R32F magnitude buffer at the image's pixel size
#   pass 2  max-reduce  -> chain of 2x downsamples down to a 1x1 peak texture
#   pass 3  compress    -> log/dynamic-range/gain -> screen (or a capture FBO)
# Splitting compression out of beamforming means the peak normalisation never
# needs a readback (no pipeline stall), and dyn-range/gain changes while frozen
# only re-run pass 3.
#
# Zoom: wheel zooms about the cursor, middle-drag (or ctrl+drag) pans, double-
# click resets.  Zoom is a shader uniform, so zooming re-beamforms the visible
# region at full screen resolution - it is a real optical zoom into the data,
# not a magnified bitmap.
#
# Calipers: drag on the image to draw a measurement line, drag either end (or
# the middle) to adjust, right-click a line to delete it.  Endpoints are stored
# in metres, so they stay pinned to the tissue through zoom, pan, resize and
# depth/sound-speed changes.
#
# Capture: grabs the current view at CAP_SCALE x the on-screen resolution into
# the side preview and the thumbnail drawer.  Captures keep the measurement
# list as geometry rather than burned-in pixels, so clicking a thumbnail
# reopens it for measuring after the fact.  FREEZE holds the last frame.
#
# Cine loop: the last CINE_SECONDS of acquisition are always in RAM - every
# completed sweep, at whatever rate the FPGA delivers them (no decimation to
# the display rate).  FREEZE stops the recorder and hands the buffer to the
# transport bar under the image: scrub the timeline to go back in time, play
# it forward at 0.1x - 4x, loop it.  What is recorded is the raw int16 RF, not
# pixels, so a replayed frame goes through the same Hilbert + beamformer as a
# live one - zoom, sound speed, dynamic range, gain, calipers and CAPTURE all
# work on the past exactly as they do on the present.
#
# Geometry: CH6-2 convex array, 67.5 mm radius, 0.3375 mm pitch, apex at (0, 0),
# elements pointing radially outward; monostatic (tx == rx), i.e. classic SAFT.
# We drive the CENTRE 48 of the probe's 192 elements, so the sub-aperture stays
# symmetric about x = 0 and _th below needs no offset term.
#
# ---------------------------------------------------------------------------
# WIRE FORMAT NOTE (N_ELEM = 48)
# ---------------------------------------------------------------------------
# The 32-element header packed the element id into bits 20:16 and left 23:21
# zero, so a header was identified by (word >> 21) == 0x708.  48 elements need
# 6 bits, which takes bit 21, so the header check here spans bits 31:22
# instead.  ctrl_decode.v emits elem[5:0] at bits 21:16 with bits 23:22 zero to
# match, and tfm_host.py / waterfall_host.py now use the same constants.  Both
# sides are derived from ELEM_BITS below - set it back to 5 and this file
# reproduces the old 32-element contract exactly.
#
# ---------------------------------------------------------------------------
# ELEMENT ID CONTRACT
# ---------------------------------------------------------------------------
# The id in the header is the one the TRANSMIT sequencer really had closed in
# the mux tree (tx_elem, latched at tx_sync), not a free-running receive
# counter, and it is an APERTURE POSITION: one end of the probe is 0 and the
# other is N_ELEM-1.  So it indexes the element geometry directly - header id i
# is the element at row i of elem_uniform() - and a sweep arrives with the id
# ascending 0..N_ELEM-1, which is what batch() splits cine snapshots on.
#
# The probe's 48 elements are NOT wired to the mux tree in array order (the
# connector scrambles them across the three leaf muxes, and within each mux the
# NO pins are out of order too).  That permutation lives entirely in
# tx_sequencer.v's mux_code() table, which is applied on the FPGA between the
# element list and the chain word.  Nothing on this side needs to know it: keep
# the two in step by leaving positions here and hardware addresses there.
#
# WHICH end is 0 is the one thing the table cannot settle - see the "flip L/R"
# toggle at ELEM_UNIFORM_FLIP below.
#
# All 48 elements transmit through the shared HV driver and receive through the
# same single AFE channel, so the receive path is identical for every one of
# them - only the mux tree moves between shots.
import ctypes as C, sys, time, threading, os, struct, collections, json
import numpy as np
import moderngl

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import (QSurfaceFormat, QImage, QPixmap, QPainter, QPen,
                           QBrush, QColor, QFont, QFontMetrics, QPolygonF,
                           QShortcut, QKeySequence)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QSlider, QPushButton,
                               QCheckBox, QHBoxLayout, QVBoxLayout, QScrollArea,
                               QFrame, QDialog, QFileDialog, QSizePolicy,
                               QLineEdit, QInputDialog)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

# PulserCtl is UI-agnostic - it only wants (send_cmd, cmd) - so the transmit
# settings are shared with tfm_host.py verbatim.  build_pulser_panel is NOT:
# it is Tk, and this host is Qt, so the panel is rebuilt below in _pulser_row().
# HELP is the same tooltip text either way, which is the part worth not forking.
from pulser_ctrl import (PulserCtl, HELP as PLS_HELP, N_ELEM_MAX,
                         T_SETTLE_MIN_US, T_INHIBIT_MIN_US,
                         ns_to_cyc as pls_ns_to_cyc,
                         us_to_cyc as pls_us_to_cyc)

#===============================================================================
# constants shared with the FPGA
#===============================================================================
XFER, NBUF        = 1024*1024, 8
PIPE_IN, PIPE_OUT = 0x82, 0x02
FT_OK, FT_OPEN_BY_INDEX = 0, 0x10

LOCK_WORD = 0xA5A55A5A
OP_START, OP_STOP, OP_RST_CNT = 0x01, 0x02, 0x03
OP_SET_SRC = 0x07
OP_SEQ_LEN, OP_SEQ_DLY, OP_SEQ_TGC = 0x0B, 0x0C, 0x0D
OP_SEQ_GAP, OP_SEQ_TGC0 = 0x0E, 0x0F
OP_PLS_TRX = 0x17           # pulser's OWN receive window, clk cycles
SRC_SEQ = 2
CLK_HZ = 100_000_000        # FPGA clk_in - delay payloads are in these cycles
FS_HZ  = 40_000_000         # AFE5804 sample rate

N_ELEM    = 48
ELEM_BITS = 6                           # bits the element id occupies at 16
ELEM_MASK = (1 << ELEM_BITS) - 1
HDR_SHIFT = 16 + ELEM_BITS              # 22: first bit above the element field
HDR_MAGIC = 0xE1 << (24 - HDR_SHIFT)    # 0x384: top byte 0xE1, guard bits zero
assert N_ELEM <= 1 << ELEM_BITS

C_DEF    = 1540.0           # m/s, soft tissue

# CH6-2, derived from the probe face rather than a datasheet: the rubber
# measures 62.32 mm end to end in a straight line (chord c) with the apex
# 7.62 mm proud of the ends (sagitta s), so
#     R   = (c^2/4 + s^2) / 2s              = 67.52 mm
#     arc = 2R * asin(c / 2R)               = 64.79 mm  (55.0 deg total)
#     pitch = arc / 192                     = 0.3375 mm
# The chord is measured over the rubber, which overhangs the active elements by
# a fraction of a mm per side, so R is biased slightly high and pitch slightly
# high with it.  Both are within ~1% - well inside what the wire-target
# calibration can trim out, and far closer than the 60 mm / 0.5 mm that were
# here before (those put the edge element 3.8 mm out of place).
PROBE_R_MM   = 67.52        # convex radius of curvature
PITCH_MM     = 0.3375       # element pitch along the arc
ACCEPT_DEF   = 30           # element acceptance half-angle, degrees

# --- t0: fixed round-trip offset the delay model does not know about ----------
# The lens and matching layer are real propagation the beamformer never sees
# (~1 mm of silicone near 1000 m/s is ~1 us one way, so ~2 us round trip), and
# the tx-start-to-capture-start offset is only known to the FPGA to a cycle.
# Both land as one constant added to every path, so one number absorbs them.
#
# This is RECONSTRUCTION ONLY - unlike the pulse->rx slider, which commands
# OP_SEQ_DLY and moves the acquisition window, t0 moves nothing on the FPGA.
# That is what makes it safe to trim against a wire target: the RF is
# untouched, so it works while frozen and on replayed cine.
#
# Positive t0 = echoes arrive LATER than the geometry predicts, so the sampler
# is pushed further into the window.  40 MHz sampling is a 25 ns bin and a
# quarter wavelength at 3.5 MHz is ~70 ns, so 10 ns steps are finer than either.
T0_NS_DEF, T0_NS_MIN, T0_NS_MAX, T0_NS_STEP = 0.0, -2000, 4000, 10
# --- apodization --------------------------------------------------------------
# Tukey fraction: 0 = rect (the old hard-edged behaviour), 1 = full Hann.  One
# number drives BOTH tapered edges, because the aperture is truncated by two
# different things depending on depth and neither may be a step:
#
#   * shallow: the acceptance cone cuts the aperture, and which elements fall
#     inside it changes from pixel to pixel.  A binary test makes an element
#     wink in or out between adjacent pixels, and the sum steps by that whole
#     element - that is what draws the faint arcs through the near field.
#   * deep: the cone is wider than the array, so the physical array end is the
#     truncation.  A rect window there puts the first sidelobe at -13 dB.
#
# Monostatic SAFT is unusually exposed to the second one.  A conventional
# tx-focus/rx-focus machine multiplies two aperture patterns, so a rect window
# lands near -26 dB two-way; SAFT sums a single aperture at doubled wavenumber,
# so it keeps the full one-way sidelobe level while it gains the 2x resolution.
# Sidelobes are the price SAFT pays for that resolution, and they show up as
# haze filling in anechoic structure.
#
# Simulated point target at 40 mm, 3.57 MHz, this array.  "clutter" is energy
# beyond 2x the main lobe, i.e. the haze; "loss" is the signal the taper costs:
#
#     apod    FWHM    clutter    loss
#       0%   0.68mm   -12.5dB   -0.4dB     <- rect, clutter swamps a 50 dB view
#      50%   0.86mm   -23.6dB   -2.7dB
#      70%   0.96mm   -35.7dB   -3.9dB     <- the knee
#      80%   1.01mm   -41.4dB   -4.6dB
#     100%   1.09mm   -46.6dB   -6.2dB     <- full Hann, 60% wider main lobe
#
# 70% is the default: 23 dB of clutter for 41% of the main lobe, and past ~80%
# the curve flattens while the signal keeps draining away.  It IS a real 3.9 dB
# of SNR, so on deep or weak targets back it off - hence the slider.
APOD_DEF = 0.7

# --- coherence factor ---------------------------------------------------------
# Apodization is the only clutter control a plain delay-and-sum beamformer has,
# and its knee is around -36 dB (the table above).  The coherence factor is the
# cheap way past that: instead of asking how much energy summed at a pixel, it
# asks how much of that energy was actually IN PHASE across the aperture, and
# scales the pixel by the answer.
#
#     CF = |sum w_i s_i|^2 / ( (sum w_i) * (sum w_i |s_i|^2) )
#
# Both sums carry the same apodization weights, so a perfectly coherent pixel -
# every element agreeing - gives CF = 1 whatever the taper is, and Cauchy-
# Schwarz bounds CF to [0, 1].  Fully incoherent contributions give
# sum(w^2)/(sum w)^2, i.e. one over the effective element count: about -34 dB
# across 48 elements, on top of whatever the apodization already bought.
#
# CF_DEF is the EXPONENT, not a blend: 0 disables it (the shader multiplies by
# CF^0 = 1 and nothing changes), 1 is the standard factor, and above 1 is more
# aggressive - each unit is roughly another 34 dB on fully incoherent energy.
#
# It defaults OFF because it changes what the image MEANS, in three ways worth
# knowing before turning it up:
#
#   * brightness stops being proportional to backscatter.  CF is a detection
#     aid, not a measurement, and full_scale() no longer describes the level
#     that reaches the screen, so the 'auto' gain reference only holds in the
#     relative sense.
#   * speckle is only partially coherent, so tissue speckle darkens along with
#     the clutter.  The image looks cleaner and loses texture that speckle
#     carries; that is a real trade, not a free win.
#   * it is unforgiving of per-element phase error.  Residual geometry error or
#     capture-start jitter lands on the TARGET as well as on the clutter around
#     it, so CF suppresses a defocused point target too.
#
# That last one makes it an instrument as well as a filter: if turning CF up
# dims the wire rather than the arc around it, the aperture is not yet in phase
# and the geometry is worth another pass.  Swept against pitch with CF at 1, the
# peak is far sharper than the envelope alone.
CF_DEF = 0.0

# --- receive bandpass ---------------------------------------------------------
# The Hilbert mask has to zero the negative half of the spectrum anyway, so
# shaping a passband into the same array is free: one extra multiply on a
# spectrum that is already in hand, no second FFT.  Without it the envelope
# carries the AFE's noise across the whole 0-20 MHz Nyquist span while the echo
# only ever occupies the probe's band, and every hertz of the difference is
# pure noise power - keeping B of the 20 MHz throws away 10*log10(20/B) dB of
# it.  4.0 +/- 2.5 MHz is 6.0 dB for nothing, on a CH6-2 whose two-way response
# is inside 2-6 MHz to begin with.
#
# It only pays where the image is NOISE-limited, which is the deep end.  The
# near field is clutter-limited - real echoes in the right band - and will not
# move, which is also how you tell the two apart: if the far field cleans up and
# the near field does not, the deep haze was electronic.
#
# The skirts are raised cosines rather than a brick wall, and that is not
# cosmetic.  A hard spectral edge rings in time, and time-domain ringing on a
# monostatic reconstruction back-projects along the isochrone as exactly the
# arcs the filter is here to reduce.  BAND_TAPER is the fraction of the
# passband spent on the two skirts together.
#
# Range resolution is c/2B, so the passband is also a resolution floor: 5 MHz
# is 0.15 mm, well inside the ~0.4 mm the two-cycle pulse already gives, but
# narrowing much past ~2 MHz starts costing real axial detail.  Centre it on
# the pulser's f0 (the readout in the transmit row) rather than on 4 MHz if you
# move the drive frequency far.
BAND_ON_DEF = True
BAND_F0_DEF, BAND_BW_DEF = 4.0, 5.0     # MHz, centre and full width
BAND_TAPER = 0.35                       # of the width, split over both skirts

# --- pulse compression (matched filter) ---------------------------------------
# The receive half of coded excitation.  With the pulser chirping, every echo
# is the whole sweep long - tens of microseconds - and the raw envelope smears
# each reflector over that length.  Cross-correlating the RF with the transmit
# waveform (multiplying the spectrum by conj(REF), inside the Hilbert FFT that
# already runs) compresses each echo back to ~1/B wide while summing the energy
# of the full sweep, which is where coded excitation's SNR gain is cashed in:
# a 20 us chirp carries ~15 dB more energy than a 2-cycle burst at the same
# voltage, and compression delivers it at c/2B axial resolution.
#
# The reference is built from the same quantised switching edges the FPGA
# fires (pulser.tx_waveform), so it tracks the chirp sliders exactly.  What it
# does NOT include is the transducer's two-way response; the bandpass above
# effectively stands in for that, and the two multiply into one weight array.
# The FFT is padded by the reference length so the correlation cannot wrap the
# deep end of the window onto the shallow end.
#
# Correlation peaks at each echo's ARRIVAL time, the same registration the
# plain envelope has, so the depth axis and t0 calibration are untouched.  It
# works on the fixed burst too (it is just a short matched filter there); it
# defaults off because with an uncoded 2-cycle burst it mostly re-shades the
# image without buying resolution.  Sidelobes of the compressed pulse ring
# AXIALLY at roughly -13 dB for an unweighted square chirp; the bandpass
# skirts double as the amplitude taper that pushes them down.
MF_ON_DEF = False

# --- sweep averaging ----------------------------------------------------------
# Coherent (pre-Hilbert) boxcar over the last M sweeps.  The echo repeats sweep
# to sweep and the noise does not, so the mean gains sqrt(M) on anything
# uncorrelated: M = 8 is 9 dB, the biggest single lever on the deep noise floor
# short of dropping f0.
#
# COHERENT is the whole point.  Averaging magnitudes after the beamformer only
# smooths speckle - by then the noise has been rectified into a positive bias,
# and no amount of averaging removes a bias.  Averaging the RF while it still
# has a sign lets the noise cancel against itself.
#
# The cost is motion.  M sweeps at ~130 sweeps/s is M * 7.7 ms of integration,
# so 8 is ~60 ms and anything moving inside that window smears.  Phantoms and
# static tissue take M as high as it goes; anything pulsatile wants 1-4.
#
# The far dBFS meter reads the AVERAGED data, which makes it a direct readout
# of how much of the deep signal was noise: step M from 1 to 8 and a
# noise-dominated far field drops ~9 dB while real tissue barely moves.
AVG_DEF, AVG_MAX = 1, 16

DEPTH_CM_DEF = 8            # ~104 us window
DLY_US_DEF   = 5            # pulse -> receive settling
GAP_US_DEF   = 50           # receive end -> next pulse (DAC ring-out)
TGC_MIN_DEF, TGC_MAX_DEF = 0, 4095
DYN_DEF, GAIN_DEF = 50, 0

ZOOM_MIN, ZOOM_MAX = 1.0, 24.0

# The ring is bounded by BOTH of these, so raising the seconds alone does
# nothing once the byte ceiling binds - it just silently keeps fewer seconds.
# Cost is ~47 MB/s at 8 cm and rises with depth (the window grows faster than
# the frame rate falls), so 40 s needs:
#
#      4 cm  1.3 GB      16 cm  2.4 GB      40 cm  2.8 GB
#      8 cm  1.9 GB      30 cm  2.7 GB
#
# 2 GB buys the full 40 s out to ~10 cm - which covers the default 8 cm working
# depth - and clamps to ~29 s at 16 cm and ~17 s at 40 cm rather than failing.
# Raise CINE_MB if you want the deep end too; the readout reports what is
# actually held, so a short loop at depth is visible rather than silent.
CINE_SECONDS = 40.0         # how far back the loop reaches
CINE_MB      = 2048         # ...and the ceiling on what that is allowed to cost
SPEED_MIN, SPEED_MAX, SPEED_DEF = 0.1, 4.0, 1.0     # replay rate vs acquisition

# |sum of N analytic signals| if every element were rail-to-rail (the Hilbert
# mask doubles the positive spectrum, hence the 2x).  Used as the reference
# when auto-gain is off, so brightness is absolute instead of per-frame.
#
# Apodization removes signal, so the reference has to shrink with it or the
# image just dims when you move the slider and "absolute" stops meaning
# anything.  A Tukey(a) tapers a fraction `a` of the aperture with a half-Hann
# of mean 0.5, so its own mean is (1 - a) + a/2 = 1 - a/2.  Only the index
# window is accounted for here: the angular taper depends on the pixel, and at
# any depth worth calibrating against the cone is wider than the array and it
# is flat at 1.0 anyway.
def full_scale(apod=None):
    a = APOD_DEF if apod is None else apod
    return float(n_alive() * 2048 * 2) * (1.0 - 0.5 * a)

# --- dead elements ------------------------------------------------------------
# Elements that receive nothing (open probe element, connector pin, or joint).
# They contribute only noise, so summing them costs SNR and drags the level
# meters, and their geometry is still perfectly good - so this is a RENDER-TIME
# mask, not a change to the acquisition:
#
#   * the FPGA keeps firing them.  Dropping them from the element list would
#     shorten the sweep and change the frame timing, and a "dead" element that
#     is really a discarded mux write (see t_inhibit) would then never get the
#     chance to come back.
#   * raw_buf and the cine recording keep their real data, so a recording made
#     now is still honest if the list turns out to be wrong.
#   * the mask indexes APERTURE POSITION, i.e. the header id and the RF texture
#     row.  That is the physical element, so it is NOT affected by "flip L/R" -
#     flip mirrors the geometry against the rows, it does not renumber them.
#
# 2026-08-14: the connector-side failures were repaired, so the old
# 1,3,4,23,25,46 default is gone and 47 of the 48 elements are summed.  Element
# 46 is the one that did NOT come back and is genuinely dead.  Everything else
# stays in - do not restore the old list without re-measuring, because a stale
# mask silently throws away part of the aperture and looks like nothing more
# than a slightly softer image.
#
# Override on the command line:  python tfm_gl_host.py dead=1,3,4
# or edit the box in the control row while running.
DEAD_DEF = "46"

def parse_dead(s):
    """Accept '1,3, 4' / '1 3 4' / empty.  Silently drops anything out of range
    so a typo in the box cannot take the window down."""
    out = set()
    for tok in str(s).replace(",", " ").split():
        try:
            v = int(tok)
        except ValueError:
            continue
        if 0 <= v < N_ELEM:
            out.add(v)
    return out

dead = {"set": set(), "gen": 0}

def n_alive():
    return max(1, N_ELEM - len(dead["set"]))

def alive_mask():
    m = np.ones(N_ELEM, dtype=np.float32)
    d = dead["set"]                 # one read: rebound, never mutated in place
    if d:
        m[sorted(d)] = 0.0
    return m

def set_dead(s):
    new = parse_dead(s)
    if new != dead["set"]:
        dead["set"] = new           # rebind, so readers never see a half-edit
        dead["gen"] += 1            # makes the GL side re-upload, like geom["gen"]

# --- gated level meters + transmit-artifact background subtraction ------------
# (same scheme as tfm_host.py - see the comments there for the reasoning)
#   near = peak of the first fifth of the window: the artifact, i.e. the
#          CLIPPING meter.  Keep it below 0 dBFS - subtraction is linear and
#          cannot remove a clipped artifact.
#   far  = RMS of everything after the near gate: the tissue detector.  Read
#          it as a delta against the air baseline at identical settings.
# The bg reference is BG_AVG averaged sweeps; each incoming row is re-aligned
# to the reference off the artifact itself (the ADC free-runs against the
# burst, so capture start jitters ~2 samples; plain subtraction would leave a
# phase-slip residue only ~6 dB down, aligned gets ~16 dB).
GATE_NEAR = 5
BG_AVG    = 16
level = {"near": -99.0, "far": -99.0}
bg    = {"ref": None, "acc": None, "n": 0, "want": 0, "on": False}

# --- per-element capture-start jitter -----------------------------------------
# The alignment above was built to make the SUBTRACTION work, but the number it
# computes is worth far more than that: it is a direct measurement of when this
# element's capture window actually opened.
#
# The artifact is produced by the same HV edge that fires tx_sync, at a fixed
# physical delay, so its position in the window IS the capture-start error.  An
# echo at round-trip time T lands at (T - T_open)*fs; if the window opened d
# early, the artifact AND every echo behind it both move +d*fs samples.  So the
# artifact is an exact fiducial for the whole trace, and shifting the row back
# by -d puts all 48 elements on one time base referenced to the burst.
#
# Two things displace the window, and this catches both:
#   * the ADC free-runs against clk_in and afe_stream's FIFO is 32 bits = two
#     samples wide, so the window can only start on a 50 ns boundary.  That is
#     the "~2 samples" in the note above, and at 3.57 MHz it is 18.5 deg RMS of
#     per-element phase error - which costs only 0.2 dB of coherent gain but
#     puts the diffuse clutter floor at sigma^2/N = -27 dB.  That is 9 dB ABOVE
#     what 70% apodization buys, i.e. the apod slider is currently masked by it.
#   * ctrl_decode's S_HDR waits for the TX FIFO to accept the header before
#     opening the window, so bus backpressure slides the range gate by the
#     stall duration.  Unbounded, and invisible to the `holes` counter, which
#     only fires when a stall outlasts the ADC FIFO's 51 us of slack.
#
# Correcting it needs a bg reference, and NOT the subtraction: the two are
# independent, so the checkbox is separate.
#
# MAXLAG is +/-8 samples = +/-200 ns.  Wider than the ~2 samples the FIFO can
# produce, because a backpressure slip is much larger; if a shift rails at the
# limit the true peak is outside the window and the row is left uncorrected
# rather than dragged to a wrong answer.
# CYCLE SKIPPING is the trap here, and it is why there are two stages below.
# The artifact is a modulated carrier, so correlating it against the reference
# finds a peak every carrier period - 11.2 samples at 3.57 MHz.  A slip of 9
# samples correlates best at -2.2 and is accepted as -2.2, confidently and
# completely wrongly.  Carrier correlation alone can only ever resolve a
# displacement modulo one period.
#
# So: a coarse ENVELOPE correlation (no carrier, no ambiguity, ~one sample of
# resolution after smoothing) first fixes which cycle we are on, then the
# carrier correlation refines inside it.  Rows where the two disagree by more
# than half a period are rejected rather than guessed at.
#
# This bounds what the correction is good for.  The 50 ns FIFO quantisation is
# a fifth of a carrier period and is handled exactly.  A backpressure gate slip
# of hundreds of ns is beyond the coarse search and shows up as railed/weak -
# detected, reported, but NOT corrected.  That one needs the S_HDR fix in RTL;
# no amount of host arithmetic recovers a window that opened microseconds late.
JIT_ON_DEF = False          # needs a reference first, so off at startup
# Correlate over a FIXED window, not the near gate.  The near gate is samps/5,
# which is 78 us at 30 cm, but the artifact is ring-down in the first ~20 us -
# everything past it is tissue echo that varies sweep to sweep and only dilutes
# the correlation.  Capping it makes the cost depth-independent (10.6 ms -> 1.8
# ms at 30 cm) and slightly improves the estimate.
JIT_GATE   = 768            # samples correlated, 19.2 us at 40 MHz
MAXLAG     = 8              # fine (carrier) search, samples
COARSE_DEC = 4              # envelope decimation before the coarse search
COARSE_LAG = 16             # coarse search, in decimated samples: +-64 raw
SUBSAMP    = 32             # phase-ramp quantisation: 1/32 samp = 0.5 deg @3.57M
JIT_MINCORR = 0.4           # normalised peak below this = no usable artifact
jit = {"rms_ns": 0.0, "pp_ns": 0.0, "railed": 0, "used": 0}

def _coarse_shift(rf, ref, g, per):
    """Envelope-domain displacement per element, in whole samples.

    |x| smoothed over one carrier period kills the carrier (and the 2*f0 ripple
    rectification leaves behind), so this correlation has a single peak and no
    period ambiguity.  Decimated by COARSE_DEC because envelope detail below a
    period is meaningless and the search is COARSE_LAG wide.  Returns NaN where
    there is nothing to lock onto."""
    w = max(2, int(round(per)))
    if g <= w + 2 * COARSE_LAG * COARSE_DEC + 2:
        return np.zeros(rf.shape[0])            # gate too short to search
    def env(a):
        c = np.cumsum(np.abs(a[:, :g]).astype(np.float64), axis=1)
        return ((c[:, w:] - c[:, :-w]) / w)[:, ::COARSE_DEC]
    x, r = env(rf), env(ref)
    m = x.shape[1]
    lo, hi = COARSE_LAG, m - COARSE_LAG
    xc = x[:, lo:hi] - x[:, lo:hi].mean(axis=1, keepdims=True)
    nlc = 2 * COARSE_LAG + 1
    cc = np.empty((rf.shape[0], nlc))
    for k in range(nlc):
        seg = r[:, lo - (k - COARSE_LAG):hi - (k - COARSE_LAG)]
        cc[:, k] = np.einsum('ij,ij->i', xc,
                             seg - seg.mean(axis=1, keepdims=True))
    best = cc.argmax(axis=1)
    flat = cc.max(axis=1) <= 0.0
    out = (best - COARSE_LAG).astype(np.float64) * COARSE_DEC
    out[flat] = np.nan
    return out

def measure_shifts(rf, ref, g):
    """Per-element displacement of this sweep's artifact against the reference,
    in fractional samples.  Positive = the artifact sits LATER in the window,
    i.e. the window opened that much EARLY.

    Integer cross-correlation over +-MAXLAG in the near gate, then parabolic
    refinement of the peak.  Returns (shift, usable, n_railed); rows whose
    correlation is too weak or whose peak rails at the search limit come back
    usable = False and shift = 0, because a wrong shift is worse than none.

    The two rejection reasons mean different things and are counted apart:
    weak = that element has no artifact to align on (dead, or badly coupled),
    RAILED = the gate slipped further than +-MAXLAG, which is a bus-backpressure
    problem and not something this correction can reach.

    This is the one place the measurement lives - the subtraction and the
    jitter correction are two consumers of the same number."""
    n = rf.shape[0]
    nl = 2 * MAXLAG + 1
    # Carrier period in samples, from the receive band centre - the user sets
    # that to the drive frequency, so it tracks a change of f0.
    per = FS_HZ / max(state["band_f0"] * 1e6, 1e5)
    coarse = _coarse_shift(rf, ref, g, per)
    # Correlate a FIXED core segment against a sliding reference, rather than
    # letting the overlap shrink with lag.  Constant length at every lag means
    # no length bias pulling the peak toward zero, and it turns the whole thing
    # into nl vectorised passes instead of n*nl scalar dot products.
    core = rf[:, MAXLAG:g - MAXLAG]                     # (n, gc)
    c = np.empty((n, nl), np.float64)
    for k in range(nl):
        # The REFERENCE slides back by L, so a peak at +L means this sweep's
        # artifact sits L samples later than the reference's.  Sliding it the
        # other way inverts the sign of everything downstream.
        L = k - MAXLAG
        c[:, k] = np.einsum('ij,ij->i', core,
                            ref[:, MAXLAG - L:g - MAXLAG - L], dtype=np.float64)
    # Normaliser for the correlation coefficient: without it a loud sweep and a
    # quiet one are not comparable and the threshold means nothing.
    nrm = np.sqrt(np.einsum('ij,ij->i', core, core, dtype=np.float64) *
                  np.einsum('ij,ij->i', ref[:, MAXLAG:g - MAXLAG],
                            ref[:, MAXLAG:g - MAXLAG], dtype=np.float64))
    kbest = c.argmax(axis=1)
    peak  = c[np.arange(n), kbest]
    good  = (nrm > 0.0) & (peak >= JIT_MINCORR * np.maximum(nrm, 1e-30))
    edge  = (kbest == 0) | (kbest == nl - 1)
    # The coarse stage owns the cycle decision.  Out past the fine search, or
    # disagreeing with it by more than half a period, means the carrier peak is
    # an alias - count it railed and leave the row alone.
    cs   = np.nan_to_num(coarse, nan=1e9)
    slip = np.abs(cs) > MAXLAG
    alias = np.abs((kbest - MAXLAG) - cs) > 0.5 * per
    edge = edge | slip | alias
    railed = int(np.count_nonzero(good & edge))
    ok = good & ~edge
    # Parabolic refinement, vectorised over the rows that survived.  Clipping
    # kbest keeps the +-1 gather in range for rejected rows; their result is
    # masked out below anyway.
    kc = np.clip(kbest, 1, nl - 2)
    i0 = np.arange(n)
    cm, c0, cp = c[i0, kc - 1], c[i0, kc], c[i0, kc + 1]
    den = cm - 2.0 * c0 + cp
    frac = np.where(den < 0.0, 0.5 * (cm - cp) / np.where(den < 0.0, den, -1.0),
                    0.0)
    s = np.where(ok, (kc - MAXLAG) + frac, 0.0).astype(np.float32)
    return s, ok, railed

def _aligned_bg(ref, s, ok):
    """`ref` with each row rolled onto this sweep's artifact phase, using the
    shifts measure_shifts() already found.  Rows without a usable shift are
    passed through unmoved, which is what the old code did on a dead element."""
    out = np.empty_like(ref)
    for i in range(ref.shape[0]):
        if not ok[i]:
            out[i] = ref[i]
            continue
        k0 = int(np.floor(s[i]))
        fr = float(s[i]) - k0
        out[i] = ((1.0 - fr) * np.roll(ref[i], k0) +
                  fr         * np.roll(ref[i], k0 + 1))
    return out

def _condition(rf, samps, live):
    """Meters + background subtraction, applied to every frame the Hilbert
    worker publishes (live and cine replay both pass through here, so a
    replayed sweep gets the same treatment the live view had).  Only live
    frames feed the reference accumulator."""
    g = samps // GATE_NEAR
    # Meter only the elements the beamformer actually uses.  A dead element is
    # noise with no echo in it, so leaving it in pulls the far RMS down and
    # makes the tissue reading look worse than the image it produced.  (near is
    # a max, so it is already immune - kept symmetric so the two always
    # describe the same set of elements.)
    d = dead["set"]                 # one read: the UI thread rebinds this
    m = rf[sorted(set(range(N_ELEM)) - d)] if d else rf
    level["near"] = 20.0 * np.log10(float(np.abs(m[:, :g]).max()) / 2048.0 + 1e-12)
    level["far"]  = 20.0 * np.log10(
        float(np.sqrt(np.mean(np.square(m[:, g:])))) / 2048.0 + 1e-12)
    if live and bg["want"] > 0:
        if bg["acc"] is None or bg["acc"].shape != rf.shape:
            bg["acc"] = np.zeros_like(rf)
            bg["n"]   = 0
        bg["acc"] += rf
        bg["n"]   += 1
        bg["want"] -= 1
        if bg["want"] == 0:
            bg["ref"], bg["acc"] = bg["acc"] / bg["n"], None
    # One measurement, up to two consumers.  Skipped entirely when neither the
    # subtraction nor the correction wants it, so the default path is unchanged.
    ref  = bg["ref"]
    have = ref is not None and ref.shape == rf.shape
    want_sub = bg["on"] and have
    want_jit = state["jit"] and have
    shifts = None
    if want_sub or want_jit:
        # The meters' near gate and the correlation window are different
        # questions: g splits near from far, JIT_GATE bounds where the artifact
        # actually lives.  Shallow windows fall back to whichever is smaller.
        s, ok, railed = measure_shifts(rf, ref, min(g, JIT_GATE))
        used = s[ok]
        jit.update(used=int(ok.sum()), railed=int(railed),
                   rms_ns=float(np.sqrt(np.mean(used * used))) / FS_HZ * 1e9
                          if used.size else 0.0,
                   pp_ns=float(used.max() - used.min()) / FS_HZ * 1e9
                         if used.size else 0.0)
        if want_sub:
            rf = rf - _aligned_bg(ref, s, ok)
        if want_jit:
            # Only the rows with a trustworthy fiducial move; the rest keep the
            # nominal timebase rather than being dragged somewhere arbitrary.
            shifts = np.where(ok, s, 0.0).astype(np.float32)
    else:
        jit.update(used=0, railed=0, rms_ns=0.0, pp_ns=0.0)
    return rf, shifts

# --- element positions/normals ------------------------------------------------
# Apex of the arc at (0, 0), +z into tissue.  R and pitch are live rather than
# frozen at import: both are measured off the probe face to ~1%, and 1% of
# pitch is half a wavelength of round-trip error at the aperture edge, which is
# exactly the sort of thing you tune by watching a wire target sharpen.  `gen`
# ticks on every rebuild so the GL side knows to re-upload the uniform.
geom = {"R_mm": PROBE_R_MM, "pitch_mm": PITCH_MM, "gen": 0}

ELEM_UNIFORM = ELEM_UNIFORM_FLIP = None
APERTURE_MM  = 0.0

def rebuild_geometry():
    global ELEM_UNIFORM, ELEM_UNIFORM_FLIP, APERTURE_MM
    R   = geom["R_mm"] * 1e-3
    _th = ((np.arange(N_ELEM) - (N_ELEM - 1) / 2.0)
           * (geom["pitch_mm"] / geom["R_mm"]))
    ex  = (R * np.sin(_th)).astype(np.float32)           # lateral, m
    ez  = (R * (np.cos(_th) - 1.0)).astype(np.float32)   # <= 0: edges curve back
    enx = np.sin(_th).astype(np.float32)                 # outward normals
    enz = np.cos(_th).astype(np.float32)
    ELEM_UNIFORM = np.stack([ex, ez, enx, enz], axis=1).astype(np.float32)  # (N,4)
    # see the array-direction note below: reversing the rows is an exact mirror
    ELEM_UNIFORM_FLIP = np.ascontiguousarray(ELEM_UNIFORM[::-1])
    APERTURE_MM = (N_ELEM - 1) * geom["pitch_mm"]
    geom["gen"] += 1

# --- array direction ----------------------------------------------------------
# Which end of the probe the FPGA calls position 0.  tx_sequencer.v's mux_code()
# table was written from a connector drawing, so the aperture order is trusted
# but its DIRECTION is not: if the drawing was read from the far side, the whole
# image comes back mirrored about x = 0 and nothing else looks wrong.
#
# _th is symmetric about zero, so EX[N-1-i] == -EX[i], ENX[N-1-i] == -ENX[i] and
# EZ / ENZ are unchanged under the reversal.  Reversing the rows is therefore
# EXACTLY a mirror of the array - no resampling, no approximation - and doing it
# here rather than on the ingest path leaves the wire ids ascending 0..N-1,
# which is what batch() splits sweeps on.  Flipping the ids instead would make
# every sample look like a sweep boundary.  (The reversal lives in
# rebuild_geometry above, since it has to be redone whenever R or pitch moves.)
rebuild_geometry()

flip = {"on": False}            # True = position 0 is the RIGHT-hand element

def elem_uniform():
    return ELEM_UNIFORM_FLIP if flip["on"] else ELEM_UNIFORM

ML, MR, MT, MB = 58, 18, 26, 36     # image margins on screen (axis gutters), px
CAP_SCALE  = 2                      # capture render scale vs on-screen image
THUMB_H    = 92

BG, PLOT_BG, FRAME_C = "#101418", "#0a0e12", "#33505f"
FG, DIM, OK_C, WARN_C = "#9ab", "#5c7080", "#77ff88", "#ffaa55"
MEAS_C, MEAS_HOT = "#ffd24a", "#ff8c3a"
MLINE_C = "#4dffd2"         # M-line: deliberately not caliper yellow

argv = [a.lower() for a in sys.argv[1:]]
mode = {"signed": any(a.startswith("sig") for a in argv)}
FORCE_SIM = any(a.startswith("sim") for a in argv)
flip["on"] = any(a.startswith("flip") for a in argv)    # startup array direction
set_dead(next((a.split("=", 1)[1] for a in argv if a.startswith("dead=")),
              DEAD_DEF))                                # dead=  (empty) uses none

#===============================================================================
# window sizing / view state
#===============================================================================
def depth_to_words(cm):
    t = 2.0 * cm / 100.0 / C_DEF               # round trip seconds
    return max(320, min(0xFFFF, int(t * FS_HZ) // 2))

cfg = {}                    # everything derived from the window length
def set_cfg(words):
    samps = 2 * words
    cfg.update(win_words=words, samps=samps, frame_words=words + 1,
               win_us=samps / FS_HZ * 1e6)
set_cfg(depth_to_words(DEPTH_CM_DEF))

# live UI state read by the render thread / shader uniforms
state = {"c": C_DEF, "dly_us": float(DLY_US_DEF), "accept": float(ACCEPT_DEF),
         "apod": float(APOD_DEF), "cf": float(CF_DEF), "t0_ns": float(T0_NS_DEF),
         "dyn": float(DYN_DEF), "gain": float(GAIN_DEF), "auto": True,
         "frozen": False, "depth_cm": DEPTH_CM_DEF,
         "band_on": bool(BAND_ON_DEF), "band_f0": float(BAND_F0_DEF),
         "band_bw": float(BAND_BW_DEF), "jit": bool(JIT_ON_DEF),
         "mf": bool(MF_ON_DEF)}

def band_edges():
    """Receive passband as (lo, hi) in Hz, clamped to the digitiser.  Returning
    the full (0, FS/2) is what 'bandpass off' looks like downstream, so nothing
    below has to special-case the checkbox."""
    if not state["band_on"]:
        return 0.0, FS_HZ / 2.0
    half = 0.5 * state["band_bw"] * 1e6
    return (max(0.0, state["band_f0"] * 1e6 - half),
            min(FS_HZ / 2.0, state["band_f0"] * 1e6 + half))

# visible window into the scene: zoom factor plus the centre it is about
view = {"zoom": 1.0, "cx": 0.0, "cz": None}

def zmax_now():
    """Deepest on-axis echo the current window can hold, in metres."""
    return state["c"] * (state["dly_us"] * 1e-6 + cfg["win_us"] * 1e-6) / 2.0

def reset_view():
    view.update(zoom=1.0, cx=0.0, cz=None)

#===============================================================================
# FT601 bring-up (identical protocol to tfm_host.py)
#===============================================================================
FT_STATUS_NAMES = {
    0: "FT_OK", 1: "FT_INVALID_HANDLE", 2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED", 4: "FT_IO_ERROR", 5: "FT_INSUFFICIENT_RESOURCES",
    6: "FT_INVALID_PARAMETER", 16: "FT_INVALID_ARGS", 17: "FT_NOT_SUPPORTED",
    18: "FT_NO_MORE_ITEMS", 19: "FT_TIMEOUT", 20: "FT_OPERATION_ABORTED",
    21: "FT_RESERVED_PIPE", 22: "FT_INVALID_CONTROL_REQUEST",
}
def ft_status(st): return FT_STATUS_NAMES.get(st, f"0x{st:X}")

class OVERLAPPED(C.Structure):
    _fields_ = [("Internal", C.c_void_p), ("InternalHigh", C.c_void_p),
                ("Pointer",  C.c_void_p), ("hEvent",       C.c_void_p)]

HW, d3, h = False, None, None
if not FORCE_SIM:
    try:
        dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "FTD3XX.dll")
        d3 = C.WinDLL(dll_path)
        d3.FT_Create.restype    = C.c_ulong
        d3.FT_WritePipe.restype = C.c_ulong
        h = C.c_void_p()
        if d3.FT_Create(C.c_void_p(0), C.c_ulong(FT_OPEN_BY_INDEX),
                        C.byref(h)) != FT_OK:
            raise OSError("FT_Create failed -- is the Ft+ enumerated?")
        HW = True
    except Exception as e:
        print(f"[no hardware: {e}]")

if not HW:
    print("running in SIMULATION mode - synthetic phantom, no FPGA.")

def send_cmd(word, name=""):
    if not HW:
        return
    buf  = (C.c_ubyte * 4).from_buffer_copy(struct.pack("<I", word & 0xFFFFFFFF))
    sent = C.c_ulong(0)
    st = d3.FT_WritePipe(h, C.c_ubyte(PIPE_OUT), buf, C.c_ulong(4),
                         C.byref(sent), None)
    if st != FT_OK or sent.value != 4:
        sys.exit(f"control write failed ({name}): "
                 f"st={st} ({ft_status(st)}) sent={sent.value}")

def cmd(op, payload=0):
    return ((op & 0xFF) << 24) | (payload & 0xFFFFFF)

def us_to_cycles(us): return int(us) * (CLK_HZ // 1_000_000)

# --- the pulser's receive window must cover ours ------------------------------
# The transmit sequencer runs on its OWN timebase: it fires the next element
# t_settle + burst + (t_ring + t_rx) later regardless of what the capture side
# is doing.  The depth slider only ever resized the CAPTURE window, so the two
# drifted apart, with two distinct failure modes:
#
#   capture cycle (dly + win + gap) > element period
#       -> the sequencer is still in S_DAMP when the next tx_sync arrives, that
#          burst is ignored, and the frame rate halves.  Harmless but slow; at
#          the 8 cm default this was already happening (159 us vs 139 us).
#
#   dly + win > element period
#       -> the capture window is still open when the NEXT element transmits, so
#          the burst and its ringdown land INSIDE the frame.  It sits at the
#          same delay in every element's window, which means the beamformer
#          sums it coherently into bright arcs across the image.  With stock
#          timing this started at 10.3 cm and got worse with depth: 20 cm swept
#          in one extra burst, 40 cm three.
#
# So size the pulser's t_rx from the capture cycle instead.  The other terms in
# the element period (t_settle, the burst, t_ring, the 6.4 us chain shift, t_CS,
# LE) are all positive and add ~15 us of extra margin, so ignoring them here is
# conservative - and it avoids duplicating the whole FSM timing model in this
# host, where pulser_ctrl could change those parameters underneath us anyway.
PLS_RX_MARGIN_US = 10       # slack on top of dly + window + gap

# The transmit settings, shared with tfm_host.py.  t_rx is the one field this
# host does NOT expose: the panel below has no "rx us" slider, because the rule
# above owns it and a manual slider would just fight the depth control.
pulser = PulserCtl(send_cmd, cmd)

def pulser_rx_us(dly_us, gap_us):
    return cfg["win_us"] + float(dly_us) + float(gap_us) + PLS_RX_MARGIN_US

def send_pls_rx(dly_us, gap_us):
    """Resize the pulser's receive window to cover ours.

    Routed through PulserCtl rather than sending OP_PLS_TRX straight out, so
    ctl.t_rx_us stays truthful - element_period_us() and frame_ms() are derived
    from it, and those drive the pacing warning.  Writing the opcode behind the
    object's back would leave both reading a stale default.
    """
    pulser.set_t_rx_us(pulser_rx_us(dly_us, gap_us))

def send_seq_config(lo, hi, dly_us, gap_us):
    """Push the full sequencer timing/TGC setup for the current window length."""
    inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
    send_cmd(cmd(OP_SEQ_LEN, cfg["win_words"]), "seq_len")
    send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(dly_us)), "seq_dly")
    send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(gap_us)), "seq_gap")
    send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
    send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")
    send_pls_rx(dly_us, gap_us)

bufs = views = ovs = got = None
if HW:
    d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))
    print("locking RX window (0xA5A55A5A)...")
    send_cmd(LOCK_WORD, "lock")
    time.sleep(0.05)
    send_cmd(cmd(OP_RST_CNT), "rst_cnt")    # implies STOP, zeroes word count
    send_cmd(cmd(OP_SET_SRC, SRC_SEQ), "set_src")
    send_seq_config(TGC_MIN_DEF, TGC_MAX_DEF, DLY_US_DEF, GAP_US_DEF)

    d3.FT_SetStreamPipe(h, C.c_int(0), C.c_int(0),
                        C.c_ubyte(PIPE_IN), C.c_ulong(XFER))
    d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_IN), C.c_ulong(1000))

    bufs  = [(C.c_ubyte * XFER)() for _ in range(NBUF)]
    views = [np.frombuffer(b, dtype=np.uint32) for b in bufs]   # zero-copy
    ovs   = [OVERLAPPED() for _ in range(NBUF)]
    got   = [C.c_ulong(0) for _ in range(NBUF)]

    def queue(i):
        d3.FT_ReadPipeEx(h, C.c_ubyte(PIPE_IN), bufs[i], C.c_ulong(XFER),
                         C.byref(got[i]), C.byref(ovs[i]))

    for i in range(NBUF):
        d3.FT_InitializeOverlapped(h, C.byref(ovs[i]))
        queue(i)
    # Transmit settings last, and arming is the last thing push_all does.  The
    # pulser owns the timebase - SRC_SEQ is slaved to tx_sync - so no frames can
    # flow until HV bursts do, and t_rx is already correct because
    # send_seq_config above ran send_pls_rx into the same PulserCtl.
    pulser.push_all()
    print(pulser.summary())
    send_cmd(cmd(OP_START), "start")        # ring armed first, THEN start
else:
    # No FPGA, so send_seq_config never ran and PulserCtl still holds the stock
    # t_rx default rather than one sized to the capture window.  Sync it anyway
    # (send_cmd is a no-op without hardware) so the derived element period and
    # the pacing guard describe the same machine the rest of the UI does -
    # otherwise simulation raises a PACING warning that is purely an artifact.
    send_pls_rx(DLY_US_DEF, GAP_US_DEF)

#===============================================================================
# shared state: reader thread <-> render
#===============================================================================
buf_lk  = threading.Lock()
raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  # full-res windows
carry   = np.empty(0, dtype=np.uint32)

class RfAverage:
    """Boxcar mean of the last N sweeps of RAW int16 RF - see AVG_DEF.

    Kept as a running int32 sum with the tail subtracted rather than a mean
    over a held window, so a push is two passes over one frame instead of N
    whatever the depth is.  int32 is exact for this: 16 sweeps of int16 peaks
    at 2^19, nowhere near the type, so the sum never drifts however long the
    machine runs (a float32 accumulator would not survive an afternoon).

    The divisor is how many sweeps are actually held, not N, so the average
    ramps in over the first N sweeps instead of showing a dark frame."""
    def __init__(self):
        self.lk  = threading.Lock()
        self.n   = int(AVG_DEF)
        self.q   = collections.deque()
        self.sum = None

    def set_n(self, n):
        # No reset: shrinking just drops the oldest frames on the next push and
        # growing keeps what it has, so dragging the slider stays continuous.
        with self.lk:
            self.n = max(1, min(int(n), AVG_MAX))

    def reset(self):
        """Discard the history.  Anything that breaks continuity between
        sweeps - a depth change, or resuming from a freeze onto a scene that
        may have moved - has to call this or the first frame back is a blend of
        two different scenes."""
        with self.lk:
            self.q.clear()
            self.sum = None

    def depth(self):
        with self.lk:
            return len(self.q)

    def push(self, frame):
        """int16 (N, samps) -> float32 (N, samps) mean.  `frame` is retained,
        so it must be a copy the caller will not write again."""
        with self.lk:
            if self.n <= 1:
                self.q.clear(); self.sum = None
                return frame.astype(np.float32)
            if self.sum is None or self.sum.shape != frame.shape:
                self.q.clear()
                self.sum = np.zeros(frame.shape, dtype=np.int32)
            self.sum += frame
            self.q.append(frame)
            while len(self.q) > self.n:
                self.sum -= self.q.popleft()
            return self.sum.astype(np.float32) / len(self.q)

rf_avg = RfAverage()

stats = {"bytes": 0, "win_bytes": 0, "t0": time.perf_counter(), "mbps": 0.0,
         "frames": 0, "win_frames": 0, "fps": 0.0, "drops": 0, "resyncs": 0,
         "seq_bad": 0, "seq_chk": 0,
         "skips": 0,
         "last_fcnt": None, "alive": True, "dirty": False}
perf  = {"gpu_ms": 0.0, "cpu_ms": 0.0, "hil_ms": 0.0}

# Hilbert hand-off: the worker publishes a whole new array each time, so the
# GL thread can grab the reference under the lock and upload it outside.
hil_lk = threading.Lock()
hil_ev = threading.Event()
hil    = {"data": None, "samps": 0, "gen": 0}

# A replay frame jumps the queue: the worker renders it instead of the live
# buffer, so scrubbing the cine loop still gets its FFTs off the UI thread.
replay_lk = threading.Lock()
replay    = {"rf": None}

def request_replay(rf):
    """Ask the Hilbert worker to publish this recorded sweep (int16 (N, samps))."""
    with replay_lk:
        replay["rf"] = rf
    hil_ev.set()

#===============================================================================
# cine loop: rolling recording of the raw RF, one entry per completed sweep
#===============================================================================
class Cine:
    """Ring of int16 RF windows, bounded by both age (CINE_SECONDS) and size
    (CINE_MB).  Slots are recycled off the tail rather than reallocated, so a
    push is one memcpy and the steady state makes no garbage.

    Storing RF instead of pixels costs ~400 kB/sweep at 8 cm depth (~50 MB/s at
    130 sweeps/s), which is what buys a replayed frame the full pipeline: it is
    re-beamformed on demand, so zoom/gain/c/calipers stay live while frozen."""
    def __init__(self):
        self.lk   = threading.Lock()
        self.buf  = collections.deque()     # (t_perf, (N, samps) int16), oldest first
        self.free = []                      # slots recycled off the tail
        self.shape, self.cap, self.fbytes = None, 1, 0
        self.recording = True

    def _configure(self, shape):
        self.shape  = tuple(shape)
        self.fbytes = int(np.prod(shape)) * 2
        self.cap    = max(8, int(CINE_MB * 1024 * 1024 // self.fbytes))

    def reset(self):
        with self.lk:
            self.buf.clear()
            self.free.clear()
            self.shape = None

    def push(self, src):
        """One completed sweep.  Called from the reader thread with buf_lk held,
        so it has to stay cheap - one ~0.1 ms copy into a recycled slot."""
        if not self.recording:
            return
        t = time.perf_counter()
        with self.lk:
            if self.shape != tuple(src.shape):      # depth changed under us
                self.buf.clear(); self.free.clear()
                self._configure(src.shape)
            while self.buf and (len(self.buf) >= self.cap or
                                t - self.buf[0][0] > CINE_SECONDS):
                self.free.append(self.buf.popleft()[1])
            a = self.free.pop() if self.free else np.empty(self.shape, np.int16)
            np.copyto(a, src)
            self.buf.append((t, a))

    def status(self):
        """(frames, seconds held, MB resident) for the readout."""
        with self.lk:
            n    = len(self.buf)
            secs = (self.buf[-1][0] - self.buf[0][0]) if n > 1 else 0.0
            mb   = (n + len(self.free)) * self.fbytes / 1e6
        return n, secs, mb

    def freeze(self):
        """Stop recording and hand out a stable, O(1)-indexable snapshot.  With
        the recorder off, nothing recycles the slots the snapshot points at."""
        self.recording = False
        with self.lk:
            items = list(self.buf)
        if not items:
            return [], np.zeros(0)
        t0 = items[0][0]
        return items, np.array([t - t0 for t, _ in items], dtype=np.float64)

    def resume(self):
        self.recording = True

cine = Cine()
_prev_elem = -1             # last element id seen, for sweep-boundary detection

def seq_check(raw16):
    """Look for holes INSIDE a receive window.

    afe_stream.v tags every 12-bit sample with a 4-bit rolling counter in the
    top nibble, and when the ADC FIFO backs up it drops whole sample pairs
    SILENTLY (afe_stream.v: `wpush <= !wfull`).  That FIFO is 1024 words deep -
    about 51 us of slack - while a receive window at 8 cm is ~104 us, so a
    stall longer than the slack punches a time hole into the middle of a trace.

    The frame still arrives with the right length and the right header, so
    frame_count stays continuous and 'drops' stays at zero.  The sequence tag
    is the ONLY evidence.  The signature is distinctive: everything before the
    hole is at the correct depth, everything after it is shifted, and the shift
    changes from frame to frame - i.e. flickering dark patches deeper in the
    window while the surface echo stays put.

    Checked on one frame per USB chunk: near enough free, and a fault happening
    often enough to see as flicker shows up within a second."""
    if raw16.shape[0] == 0:
        return
    t = (raw16[0] >> 12).astype(np.int16)        # tag counts +1 per SAMPLE
    d = np.diff(t)
    stats["seq_bad"] += int(np.count_nonzero((d != 1) & (d != -15)))
    stats["seq_chk"] += 1

def batch(fr):
    """fr: (m, frame_words) uint32, all rows verified to start with a header."""
    global _prev_elem
    hdr   = fr[:, 0]
    elems = ((hdr >> 16) & ELEM_MASK).astype(np.int32)
    fcnt  = (hdr & 0xFFFF).astype(np.int64)
    if stats["last_fcnt"] is not None and \
       ((int(fcnt[0]) - stats["last_fcnt"]) & 0xFFFF) != 1:
        stats["drops"] += 1
    stats["drops"] += int(np.count_nonzero((np.diff(fcnt) & 0xFFFF) != 1))
    stats["last_fcnt"] = int(fcnt[-1])

    # Elements the sequencer SKIPPED.  If a capture overruns, the next tx_sync
    # arrives while the FSM is still busy and that burst is ignored: the frame
    # counter stays continuous (nothing was lost on the wire) so `drops` sees
    # nothing, but the element id sequence gains a hole and that element keeps
    # last sweep's data in raw_buf.  A stale element is decorrelated against
    # anything that moved, which is per-frame clutter - so this is the counter
    # that measures the boiling, and it is invisible to `drops` and `holes`.
    de = np.diff(elems)
    stats["skips"] += int(np.sum(de[de > 1] - 1))

    raw16 = np.ascontiguousarray(fr[:, 1:]).view(np.uint16)
    seq_check(raw16)
    u = (raw16 & 0x0FFF).astype(np.int32)
    c = np.where(u >= 2048, u - 4096, u) if mode["signed"] else u - 2048
    c = c.astype(np.int16)
    keep = elems < N_ELEM                   # ignore ids the array cannot hold

    # raw_buf is written in place, so the only instant it holds one coherent
    # sweep is just before the element id wraps.  Split the chunk there and
    # snapshot in the gaps - that records every sweep, at the acquisition rate,
    # rather than whatever the display happened to sample.  A chunk spans ~2-3
    # sweeps at 8 cm, so this loop runs a couple of times per 1 MB transfer.
    wraps = np.nonzero(np.diff(np.concatenate(([_prev_elem], elems))) < 0)[0]
    lo = 0
    for w in wraps:
        w = int(w)
        k = keep[lo:w]
        raw_buf[elems[lo:w][k]] = c[lo:w][k]
        cine.push(raw_buf)
        lo = w
    k = keep[lo:]
    raw_buf[elems[lo:][k]] = c[lo:][k]
    _prev_elem = int(elems[-1])

    stats["frames"]     += fr.shape[0]
    stats["win_frames"] += fr.shape[0]
    stats["dirty"] = True
    hil_ev.set()

def process(words):
    """Frame parser.  Fast path: back-to-back aligned frames, fully vectorized.
    A header is 0xE1 in the top byte with the guard bits above the element
    field zero -> (word >> HDR_SHIFT) == HDR_MAGIC."""
    global carry
    with buf_lk:
        FW = cfg["frame_words"]
        w = np.concatenate((carry, words)) if carry.size else words
        pos, n = 0, w.size
        while n - pos >= FW:
            nfr  = (n - pos) // FW
            hdrs = w[pos : pos + nfr*FW : FW]
            ok   = (hdrs >> HDR_SHIFT) == HDR_MAGIC
            if ok.all():
                batch(w[pos : pos + nfr*FW].reshape(nfr, FW))
                pos += nfr * FW
            else:
                bad = int(np.argmin(ok))            # first non-header
                if bad > 0:
                    batch(w[pos : pos + bad*FW].reshape(bad, FW))
                    pos += bad * FW
                else:                               # lost sync: hunt for a header
                    stats["resyncs"] += 1
                    nxt = np.nonzero((w[pos+1:] >> HDR_SHIFT) == HDR_MAGIC)[0]
                    if nxt.size == 0:
                        pos = n
                        break
                    pos += 1 + int(nxt[0])
        carry = w[pos:].copy()                      # partial frame -> next chunk

def reader():
    n = C.c_ulong(0)
    while stats["alive"]:
        for i in range(NBUF):
            if d3.FT_GetOverlappedResult(h, C.byref(ovs[i]), C.byref(n),
                                         C.c_int(1)) != FT_OK:
                if stats["alive"]:
                    print("read error - stream stopped")
                    stats["alive"] = False
                return
            nb = n.value
            nw = nb // 4
            if nw:
                process(views[i][:nw])          # done before the buffer requeues
                stats["bytes"]     += nb
                stats["win_bytes"] += nb
            queue(i)
        dt = time.perf_counter() - stats["t0"]
        if dt >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt / 1e6
            stats["fps"]  = stats["win_frames"] / dt
            stats["win_bytes"], stats["win_frames"] = 0, 0
            stats["t0"] = time.perf_counter()

def sim_reader():
    """Synthetic phantom so the UI can be exercised without the FPGA: a handful
    of point scatterers plus noise, re-rendered at ~30 sweeps/s.

    The scatterers are placed against the array's TRUE geometry - the module
    constants - not against `geom`, which is what the sliders drag around.
    Keeping the two apart is the point: mistune R, pitch, c or t0 and the
    simulated targets smear exactly the way real ones do, so the wire-target
    calibration can be rehearsed with no probe attached.  Truth here has no
    lens delay, so t0 is correct at 0.
    """
    scat = [(0.000, 0.020), (0.010, 0.034), (-0.013, 0.048),
            (0.005, 0.062), (-0.004, 0.013), (0.017, 0.075)]
    _R  = PROBE_R_MM * 1e-3
    _th = (np.arange(N_ELEM) - (N_ELEM - 1) / 2.0) * (PITCH_MM / PROBE_R_MM)
    tx  = (_R * np.sin(_th)).astype(np.float32)
    tz  = (_R * (np.cos(_th) - 1.0)).astype(np.float32)
    while stats["alive"]:
        with buf_lk:
            samps, c = cfg["samps"], state["c"]
        t = (np.arange(samps, dtype=np.float32) / FS_HZ)[None, :]
        a = np.zeros((N_ELEM, samps), np.float32)
        dly_s = state["dly_us"] * 1e-6
        for (sx, sz) in scat:
            d   = np.hypot(sx - tx, sz - tz).astype(np.float32)
            tof = (2.0 * d / c - dly_s)[:, None]
            dt  = t - tof
            a  += 900.0 * np.exp(-(dt / 2.5e-7) ** 2) * np.cos(2*np.pi*5e6 * dt)
        a += np.random.normal(0.0, 35.0, a.shape).astype(np.float32)
        with buf_lk:
            if cfg["samps"] == samps:
                raw_buf[:] = np.clip(a, -2048, 2047).astype(np.int16)
                cine.push(raw_buf)          # one synthetic sweep == one frame
                stats["dirty"] = True
                hil_ev.set()
                stats["frames"] += N_ELEM
                stats["win_frames"] += N_ELEM
                stats["bytes"] += samps * 2 * N_ELEM
                stats["win_bytes"] += samps * 2 * N_ELEM
        dt_w = time.perf_counter() - stats["t0"]
        if dt_w >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt_w / 1e6
            stats["fps"]  = stats["win_frames"] / dt_w
            stats["win_bytes"], stats["win_frames"] = 0, 0
            stats["t0"] = time.perf_counter()
        time.sleep(1.0 / 30.0)

threading.Thread(target=reader if HW else sim_reader, daemon=True).start()

#===============================================================================
# M-mode
#===============================================================================
# A segment drawn on the B-mode, resampled once per SWEEP and scrolled right to
# left.  Drawn radially it is classic M-mode; drawn any other way it is a
# generalised position-vs-time strip, which is the same thing the calipers
# already let you do spatially.
#
# WHY THIS IS ON THE CPU rather than a second GL pass over mag_tex: M-mode is a
# TIME instrument.  Reading the rendered image back would sample it at the
# display rate (~60 Hz, and irregular - it stalls when the window is occluded),
# whereas the acquisition delivers a fresh sweep every 8.5 ms.  Sampling the RF
# directly gives one column per sweep at the rate the hardware actually
# produces them, which is both finer and, more importantly, EVENLY SPACED - the
# audio below is built from the column-to-column difference and would be
# rubbish if the interval wandered with frame timing.  It also avoids a
# glReadPixels sync point in a pipeline explicitly built not to have one.
#
# The cost is that mline_sample() duplicates the beamformer in numpy.  It is a
# transcription of the BEAMFORM shader - same delays, same Tukey windows, same
# acceptance test, same coherence factor - and the two MUST be kept in step or
# the strip stops describing the image above it.  Any change to the shader's
# element loop needs the same change here.
# 256 rows already exceeds the strip's tallest on-screen height, and this runs
# inside the per-sweep budget alongside the Hilbert transform - going finer buys
# nothing visible and risks the worker falling behind the acquisition.
MM_PTS   = 256              # samples along the line (the strip's vertical axis)
MM_COLS  = 1200             # history depth; at ~117 sweeps/s that is ~10 s

mm_lk = threading.Lock()
mm = {"buf":  np.zeros((MM_PTS, MM_COLS), np.float32),
      "t":    np.zeros(MM_COLS, np.float64),   # perf_counter per column
      "w": 0, "n": 0, "prev": None, "peak": 1e-9}

# Endpoints in metres, like the calipers, so the line stays pinned to the
# tissue through zoom, pan, resize and depth changes.
mline = {"on": False, "a": None, "b": None, "err": None}

# What the synthesiser reads: motion energy, and where along the line it is.
audio_fb = {"amp": 0.0, "pos": 0.5}

def _ramp(v):
    """Half-Hann, matching ramp() in the shader."""
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(v, 0.0, 1.0))

def mline_sample(an, samps, a, b, npts=MM_PTS):
    """(N, samps, 2) analytic RF -> (npts,) envelope along the segment a..b.

    Transcription of the BEAMFORM fragment shader; see the note above."""
    E     = elem_uniform()                              # (N,4) x, z, nx, nz
    alive = alive_mask()                                # (N,)
    f     = np.linspace(0.0, 1.0, npts, dtype=np.float32)
    px    = a[0] + (b[0] - a[0]) * f
    pz    = a[1] + (b[1] - a[1]) * f

    dvx = px[:, None] - E[None, :, 0]                   # (M,N)
    dvz = pz[:, None] - E[None, :, 1]
    d   = np.hypot(dvx, dvz)
    ds  = np.maximum(d, 1e-9)

    # tx == rx: round trip is 2*d, capture starts dly_s after the fire, t0_s is
    # the lens/electronic offset the geometry cannot see.
    t    = (2.0 * d / state["c"] + state["t0_ns"] * 1e-9
            - state["dly_us"] * 1e-6) * FS_HZ
    cosa = (dvx * E[None, :, 2] + dvz * E[None, :, 3]) / ds
    cacc = float(np.cos(np.radians(state["accept"])))
    ok   = ((t >= 0.0) & (t <= samps - 1.0) & (cosa >= cacc) &
            (alive[None, :] > 0.5))

    ap = max(state["apod"], 1e-4)
    v  = np.abs(2.0 * (np.arange(N_ELEM, dtype=np.float32) / (N_ELEM - 1.0)) - 1.0)
    w  = (_ramp((1.0 - v) / ap)[None, :] *
          _ramp(((cosa - cacc) / max(1.0 - cacc, 1e-6)) / ap))
    w  = np.where(ok, w, 0.0).astype(np.float32)

    # Fractional-delay tap, the CPU's version of the shader's bilinear fetch.
    # Flatten to (N*samps, 2) and gather with take(): 2-D fancy indexing on the
    # (N, samps, 2) array costs ~60% more, and this runs inside the per-sweep
    # budget so it is worth the extra line.
    ti   = np.clip(t, 0.0, samps - 2.0)
    i0   = ti.astype(np.int32)
    fr   = (ti - i0)[..., None].astype(np.float32)
    flat = an.reshape(N_ELEM * samps, 2)
    k    = (np.arange(N_ELEM, dtype=np.int64) * samps + i0).ravel()
    s    = (flat.take(k, axis=0).reshape(npts, N_ELEM, 2) * (1.0 - fr) +
            flat.take(k + 1, axis=0).reshape(npts, N_ELEM, 2) * fr)   # (M,N,2)

    acc = np.einsum('mn,mnk->mk', w, s)                 # (M,2) complex sum
    mag = np.hypot(acc[:, 0], acc[:, 1])
    if state["cf"] > 0.0:
        wsum = w.sum(axis=1)
        psum = (w * (s * s).sum(axis=2)).sum(axis=1)
        cf   = (acc[:, 0]**2 + acc[:, 1]**2) / np.maximum(wsum * psum, 1e-20)
        mag  = mag * np.power(np.clip(cf, 0.0, 1.0), state["cf"])
    return mag.astype(np.float32)

#===============================================================================
# reverberation scan
#===============================================================================
# Multiple reflections are PERIODIC in range, and that is the only property
# that separates them from everything else in the image.  A layer at depth d
# that bounces off the probe face comes back at 2d, 3d, 4d...; two layers dz
# apart ring at dz spacing.  So a strong peak in the autocorrelation of the
# range profile, at some lag L, says "something in this image repeats every
# L mm" - and tissue does not do that.
#
# Three things make it read cleanly rather than being buried:
#
#   * dB, not linear.  Each bounce multiplies the amplitude by the same
#     reflection coefficient, so the multiples decay geometrically and only the
#     first one or two survive a linear autocorrelation.  In dB the decay is a
#     straight line and every multiple carries equal weight.
#   * cubic detrend.  Attenuation and the TGC ramp are a smooth trend in dB; if
#     left in they produce a huge triangular pedestal that swamps the peaks.  A
#     low-order polynomial removes them without touching periodicity at any lag.
#   * average over radial lines.  Speckle decorrelates laterally within a
#     resolution cell, so averaging drives it down as 1/sqrt(lines), while
#     reverberation is laterally extended and stays put.  This is what turns a
#     hint into a peak.
#
# Radial because that is the propagation direction: on a convex array the rays
# fan out from the centre of curvature at (0, -R), not straight down.
# 24 lines, not 12: measured against synthetic speckle, doubling the lines took
# detection of a strong multiple from 38% to 68% and dropped false positives to
# zero, for 55 ms a scan.  Sensitivity is bought almost entirely here.
RVB_LINES  = 24             # radial lines averaged
RVB_PTS    = 512            # samples along each line
RVB_MIN_MM = 2.0            # shortest period worth reporting
RVB_MAXFRAC = 0.45          # longest lag examined, as a fraction of the span
# Harmonics summed by the comb.  Physically motivated: each bounce costs the
# reflection coefficient twice, so only 3-5 orders ever clear the speckle.
# Summing every harmonic that fits (the obvious choice) adds pure noise terms
# for short periods and buries them - 10 mm goes from undetected to 3.7 sigma
# just by capping this at 4.
RVB_MAXORD = 4
# Thresholds calibrated against the measured null, NOT assumed from Gaussian
# statistics: ~220 candidate lags are scanned and the best taken, so the naive
# 3 sigma fires on 12% of pure-speckle images.  Over 60 speckle-only trials the
# z-max distribution was median 2.4, 95th 3.4, max 3.8.  Hence 3.5 to report at
# all (~0-4% false alarm) and 4.5 before calling it strong.
#
# Be aware this detector is SPECIFIC, not sensitive: at 3.5 it catches a strong
# multiple (-6 dB/bounce) about two thirds of the time and a -9 dB/bounce one
# only ~10%.  A peak means something; a null means little, so the text below
# says so rather than declaring the image clean.
RVB_Z_REPORT = 3.5
RVB_Z_STRONG = 4.5

def reverb_rays(z0, z1, n_lines):
    """(a, b) endpoints of n_lines rays, z0..z1 metres along each radius."""
    R    = geom["R_mm"] * 1e-3
    half = (N_ELEM - 1) * 0.5 * geom["pitch_mm"] / geom["R_mm"]   # radians
    th   = np.linspace(-half, half, n_lines)
    fx, fz = R * np.sin(th), R * (np.cos(th) - 1.0)   # the probe face
    ux, uz = np.sin(th), np.cos(th)                   # outward radial unit
    return [((fx[i] + z0*ux[i], fz[i] + z0*uz[i]),
             (fx[i] + z1*ux[i], fz[i] + z1*uz[i])) for i in range(n_lines)]

def _autocorr(x):
    n  = x.size
    nf = next_fast_len(2 * n)
    X  = np.fft.rfft(x, nf)
    r  = np.fft.irfft(X * np.conj(X), nf)[:n]
    return r / max(float(r[0]), 1e-30)

def reverb_scan(an, samps):
    """Beamform a fan of radial lines and hunt for periodicity in range.

    Returns a dict for the dialog to draw, or None if there is nothing to look
    at.  Runs off the UI timer at a few Hz, not per sweep - it is a diagnostic,
    and RVB_LINES beamformed lines is far too much work for the frame budget."""
    if an is None or samps <= 0:
        return None
    # Start past the ring-down: that end of the window is transmit artifact, and
    # its own decay is a trend, not a reverberation.
    z0 = max(state["c"] * (state["dly_us"] * 1e-6) / 2.0, 4e-3) + 3e-3
    z1 = zmax_now()
    if z1 <= z0 + 5e-3:
        return None
    prof = np.zeros(RVB_PTS, np.float64)
    acc  = np.zeros(RVB_PTS, np.float64)
    used = 0
    for a, b in reverb_rays(z0, z1, RVB_LINES):
        mag = mline_sample(an, samps, a, b, RVB_PTS)
        if not np.any(mag > 0.0):
            continue
        db = 20.0 * np.log10(mag.astype(np.float64) + 1e-9)
        prof += db
        k = np.arange(RVB_PTS, dtype=np.float64)
        db = db - np.polyval(np.polyfit(k, db, 3), k)     # kill the trend
        acc  += _autocorr(db)
        used += 1
    if not used:
        return None
    prof /= used
    acc  /= used

    span_mm = (z1 - z0) * 1e3
    step_mm = span_mm / (RVB_PTS - 1)
    lag_mm  = np.arange(RVB_PTS) * step_mm
    lo = max(int(np.ceil(RVB_MIN_MM / step_mm)), 2)
    hi = int(RVB_PTS * RVB_MAXFRAC)
    peaks = []
    if hi > lo + 4:
        seg = acc[lo:hi]
        # Robust baseline.  mean/std would be inflated by the very peaks being
        # hunted - a short period puts six harmonics inside the search range,
        # which drags the threshold up above them and hides itself.
        base = float(np.median(seg))
        sig  = 1.4826 * float(np.median(np.abs(seg - base))) or 1e-9
        # Comb score.  Reverberation is DEFINED by repeating at 2L, 3L, ..., so
        # score a candidate period by its whole harmonic series instead of one
        # lag.  Dividing by sqrt(count) keeps unit noise variance whatever
        # number of harmonics fit, so short and long periods compete fairly;
        # testing lags independently under-detects exactly the short periods a
        # probe-face multiple produces.  Speckle has no harmonics and gains
        # nothing here, which is what widens the gap.
        z = np.zeros(hi - lo)
        for m in range(lo, hi):
            h = np.arange(m, acc.size, m)[:RVB_MAXORD]
            z[m - lo] = (acc[h] - base).sum() / (np.sqrt(h.size) * sig)
        for i in range(1, z.size - 1):
            if z[i] > z[i-1] and z[i] >= z[i+1] and z[i] > RVB_Z_REPORT:
                peaks.append((float(lag_mm[lo + i]), float(seg[i]), float(z[i])))
        peaks.sort(key=lambda t: -t[2])
        peaks = peaks[:4]
    return {"z0_mm": z0 * 1e3, "z1_mm": z1 * 1e3, "prof": prof.astype(np.float32),
            "lag_mm": lag_mm.astype(np.float32), "acc": acc.astype(np.float32),
            "lo": lo, "hi": hi, "peaks": peaks, "lines": used}

def mm_reset():
    """Line moved (or depth changed): the history no longer describes one place."""
    with mm_lk:
        mm["buf"][:] = 0.0
        mm["w"], mm["n"], mm["prev"], mm["peak"] = 0, 0, None, 1e-9
    audio_fb["amp"] = 0.0

def mm_push(col):
    """One sweep's worth of line, plus the motion feature the audio runs on."""
    now = time.perf_counter()
    with mm_lk:
        i = mm["w"]
        mm["buf"][:, i] = col
        mm["t"][i]      = now
        mm["w"] = (i + 1) % MM_COLS
        mm["n"] = min(mm["n"] + 1, MM_COLS)
        prev, mm["prev"] = mm["prev"], col
        # Slowly-decaying peak: the strip's own auto-gain reference.  Decay so a
        # single bright transient does not dim the next ten seconds of history.
        mm["peak"] = max(float(col.max()), mm["peak"] * 0.999)

    if prev is None or prev.shape != col.shape:
        return
    # Frame-to-frame change IS the motion: a stationary scatterer subtracts to
    # zero however bright it is, so the audio responds to movement rather than
    # to echogenicity.
    dif = np.abs(col - prev)
    tot = float(dif.sum())
    audio_fb["amp"] = float(np.sqrt(np.mean(dif * dif)))
    if tot > 1e-12:                     # centroid of the motion along the line
        audio_fb["pos"] = float((dif * np.arange(dif.size)).sum()
                                / tot / max(dif.size - 1, 1))

def hilbert_worker():
    """The analytic-signal transform is the only CPU-heavy step left (~6 ms for
    48 elements with numpy).  Run it here rather than in paintGL so it never
    stalls the UI, and not in the reader thread so it never delays requeueing a
    USB buffer.  Publishes a fresh array per sweep; the GL thread just uploads
    whatever generation it finds.

    Replay requests pre-empt the live buffer, so scrubbing the cine loop runs
    through exactly the same transform - and off the UI thread as well."""
    while stats["alive"]:
        hil_ev.wait(0.1)
        hil_ev.clear()
        if not stats["alive"]:
            return
        with replay_lk:
            rep = replay["rf"]
            replay["rf"] = None
        if rep is not None:
            samps = rep.shape[1]
            t0 = time.perf_counter()
            cond, sh = _condition(rep.astype(np.float32), samps, live=False)
            out = analytic(cond, samps, sh)
            perf["hil_ms"] = (time.perf_counter() - t0) * 1e3
            with hil_lk:
                hil.update(data=out, samps=samps, gen=hil["gen"] + 1)
            continue
        if state["frozen"]:
            continue                    # frozen: nothing will look at the result
        with buf_lk:
            if not stats["dirty"]:
                continue
            stats["dirty"] = False
            samps = cfg["samps"]
            rf = raw_buf.copy()         # int16: the averager sums it exactly
        # Averaging goes here, not in the reader: the copy above is already off
        # the USB path, and the cine ring keeps storing RAW sweeps so a recorded
        # loop can be re-averaged (or not) at replay time.
        rf = rf_avg.push(rf)
        t0 = time.perf_counter()
        cond, sh = _condition(rf, samps, live=True)
        out = analytic(cond, samps, sh)
        perf["hil_ms"] = (time.perf_counter() - t0) * 1e3
        if state["frozen"]:             # froze mid-transform: do not stomp the
            continue                    # frame the user just paused on
        # Live sweeps only.  A replayed frame would push a column stamped with
        # the wall clock rather than its acquisition time, so scrubbing the cine
        # loop would shuffle the strip's time axis into nonsense.
        a, b = mline["a"], mline["b"]
        if mline["on"] and a is not None and b is not None:
            try:
                mm_push(mline_sample(out, samps, a, b))
            except Exception as e:      # a bad line must never kill the worker
                # Disarming silently is worse than the original fault: the
                # checkbox stays ticked over a dead strip and every drag falls
                # through to the caliper tool, so it presents as "M-mode does
                # nothing" with the real error only on stdout, where a GUI user
                # never sees it.  Hand it to _tick to surface.
                print(f"[m-mode: {e}]")
                mline["err"] = str(e)
                mline["on"] = False
        with hil_lk:
            hil.update(data=out, samps=samps, gen=hil["gen"] + 1)
# started below, once analytic() exists

#===============================================================================
# analytic signal (the one piece of per-frame CPU work left)
#===============================================================================
def next_fast_len(n):
    """Smallest 5-smooth number >= n.  np.fft on the raw window length can be
    several times slower (e.g. 4154 = 2*31*67); padding to 2^a*3^b*5^c fixes
    it and only perturbs the Hilbert transform near the window edges."""
    best = 1 << n.bit_length()
    p5 = 1
    while p5 < best:
        p3 = p5
        while p3 < best:
            p2 = p3
            while p2 < n:
                p2 *= 2
            best = min(best, p2)
            p3 *= 3
        p5 *= 5
    return best

try:                        # optional: ~2x faster here, because scipy keeps
    from scipy.fft import fft as _fft, ifft as _ifft      # float32 -> complex64
    _FFT_KW = {"workers": -1}                             # while numpy always
    FFT_LIB = "scipy"                                     # promotes to float64
except ImportError:
    _fft, _ifft, _FFT_KW, FFT_LIB = np.fft.fft, np.fft.ifft, {}, "numpy"

def _hilb_mask(nfft, lo_hz, hi_hz):
    """Hilbert spectrum mask - DC and Nyquist at 1, the positive bins at 2, the
    negative half at 0 - with the receive passband folded straight into it.

    Full band in gives back the plain analytic mask bit for bit, so 'bandpass
    off' costs nothing and is not a separate code path."""
    wgt = np.zeros(nfft, dtype=np.float64)
    wgt[0] = 1.0; wgt[nfft//2] = 1.0; wgt[1:nfft//2] = 2.0
    if lo_hz > 0.0 or hi_hz < FS_HZ / 2.0:
        f = np.arange(nfft, dtype=np.float64) * (FS_HZ / nfft)   # bin centre, Hz
        t = max(BAND_TAPER * 0.5 * (hi_hz - lo_hz), 1.0)         # skirt width
        # Same half-Hann ramp the shader apodizes with, on the frequency axis:
        # 0 outside the band, 1 across the flat top, no corner at either edge.
        r = lambda v: 0.5 - 0.5 * np.cos(np.pi * np.clip(v, 0.0, 1.0))
        wgt *= r((f - lo_hz) / t) * r((hi_hz - f) / t)
    return wgt.astype(np.float32)      # float32 keeps the multiply in complex64

# --- sub-sample time shift ----------------------------------------------------
# A shift of d samples is exp(-2j*pi*k*d/nfft) on the spectrum, so correcting a
# measured displacement s means multiplying by exp(+2j*pi*k*s/nfft).  Building
# that (48, nfft) array per frame costs 12 ms at 8 cm and 45 ms at 30 cm - far
# too slow - so the shift is split:
#
#   integer part   -> np.roll on the real trace before the FFT (a memory move)
#   fractional part-> one of SUBSAMP precomputed ramps, selected per element
#
# 1/32 of a sample is 0.39 ns, i.e. 0.5 deg at 3.57 MHz, against the ~18 deg
# RMS being corrected.  Measured cost of the table path is 0.6 ms at 8 cm and
# 1.8 ms at 30 cm, and the table itself is 1-4 MB rebuilt only when nfft moves.
#
# The roll wraps a few samples around the window edge.  That is the same
# approximation _aligned_bg has always made, and it lands in the ring-down at
# one end and past the deepest echo at the other.
# NB: not `_ramp` - that name is already the half-Hann apodization helper used
# by the numpy beamformer transcription, and shadowing it breaks M-mode.
_fracramp = {"nfft": 0, "tbl": None}

def _frac_ramps(nfft):
    """tbl[j] delays by j/SUBSAMP of a sample.  DELAY, i.e. the same direction
    as the np.roll that handles the integer part - the two have to compose, and
    getting this sign backwards costs a full sample of error on the fractional
    remainder while leaving integer shifts looking perfect."""
    if _fracramp["nfft"] != nfft:
        j = np.arange(SUBSAMP, dtype=np.float64) / SUBSAMP
        k = np.arange(nfft, dtype=np.float64)
        _fracramp.update(nfft=nfft,
                     tbl=np.exp((-2j * np.pi / nfft) *
                                np.outer(j, k)).astype(np.complex64))
    return _fracramp["tbl"]

_roll_buf = {"shape": None, "buf": None}

def _roll_rows(rf, k0):
    """Per-row circular shift into a cached buffer.  np.roll + np.stack would
    move ~9 MB per frame at 30 cm (roll concatenates, stack copies again); two
    slice assignments into a buffer that is allocated once does it in one."""
    if _roll_buf["shape"] != rf.shape:
        _roll_buf.update(shape=rf.shape, buf=np.empty_like(rf))
    out = _roll_buf["buf"]
    for i in range(rf.shape[0]):
        k = int(k0[i])
        if k == 0:
            out[i] = rf[i]
        elif k > 0:
            out[i, :k] = rf[i, -k:]
            out[i, k:] = rf[i, :-k]
        else:
            out[i, k:] = rf[i, :-k]
            out[i, :k] = rf[i, -k:]
    return out

def _split_shift(s):
    """s -> (integer roll, fractional table index), with the rounding carried
    into the integer part so index SUBSAMP can never be selected."""
    k0 = np.floor(s).astype(np.int32)
    j  = np.rint((s - k0) * SUBSAMP).astype(np.int32)
    k0 += j // SUBSAMP                  # frac rounded up to a whole sample
    return k0, j % SUBSAMP

_mf_ref = {"gen": None, "ref": None}
def mf_reference():
    """Transmit waveform at the ADC rate, cached against pulser.tx_gen so it
    rebuilds exactly when a burst/chirp setting is sent and never else."""
    if _mf_ref["gen"] != pulser.tx_gen:
        _mf_ref.update(gen=pulser.tx_gen,
                       ref=np.asarray(pulser.tx_waveform(FS_HZ),
                                      dtype=np.float32))
    return _mf_ref["ref"]

_hilb = {"key": None, "wgt": None}
def analytic(rf, samps, shifts=None):
    """(N, samps) real -> (N, samps, 2) float32 interleaved re/im.

    The only per-frame CPU work in the whole pipeline (~6 ms for 48 elements
    with numpy, ~3 ms with scipy installed).  Everything else is on the GPU.

    The mask is cached on (length, passband, matched filter), so dragging the
    band sliders rebuilds one array per change and the steady state is
    unchanged.  With pulse compression on, conj(FFT(reference)) is folded into
    the same weight - the correlation costs nothing per frame beyond the FFT
    padding that stops it wrapping the window ends onto each other.

    `shifts`, if given, is the per-element capture-start displacement in
    samples from measure_shifts(); each row is moved back by -shift so all 48
    land on one timebase referenced to the transmit burst."""
    mf   = state["mf"]                 # read ONCE, like the band below
    ref  = mf_reference() if mf else None
    nfft = next_fast_len(samps + (ref.size if mf else 0))
    key  = (nfft, mf, _mf_ref["gen"] if mf else None) + band_edges()
    if _hilb["key"] != key:            # the UI thread moves the settings, and
        wgt = _hilb_mask(nfft, *key[3:])            # key and weight must agree
        if mf:
            # Divide by the reference energy so a perfect echo compresses to
            # its own amplitude rather than to (amplitude * sum ref^2) - the
            # brightness scale stays comparable when the checkbox is toggled.
            R   = np.fft.fft(ref.astype(np.float64), nfft)
            wgt = (wgt * np.conj(R) /
                   max(float(np.dot(ref, ref)), 1e-9)).astype(np.complex64)
        _hilb.update(key=key, wgt=wgt)
    if shifts is not None:
        k0, j = _split_shift(-np.asarray(shifts, dtype=np.float64))
        if np.any(k0):
            rf = _roll_rows(rf, k0)
    X = _fft(rf, n=nfft, axis=1, **_FFT_KW)
    X *= _hilb["wgt"]
    if shifts is not None:
        # Per-element, so it cannot broadcast; the loop avoids materialising a
        # (48, nfft) gather, which at 30 cm would be 6 MB of traffic per frame.
        # The mask has already zeroed k > nfft/2, so the ramp only has to be
        # correct on the positive half - which it is, by construction.
        tbl = _frac_ramps(nfft)
        for i in range(X.shape[0]):
            if j[i]:
                X[i] *= tbl[j[i]]
    an = _ifft(X, axis=1, **_FFT_KW)[:, :samps]
    out = np.empty((N_ELEM, samps, 2), dtype=np.float32)
    out[..., 0] = an.real
    out[..., 1] = an.imag
    return out

threading.Thread(target=hilbert_worker, daemon=True).start()

#===============================================================================
# shaders
#===============================================================================
VERT = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

# One thread per output pixel; the element loop lives in registers and every
# A-scan fetch is a hardware bilinear tap, so the delay is applied at fractional
# sample resolution instead of being rounded to the nearest sample.
# `viewbox` is the visible slab of tissue (x0, x1, z0, z1) in metres - zooming
# just narrows it, so the reconstruction always fills the screen's real pixels.
BEAMFORM = """
#version 330
in vec2 v_uv;
out float f_mag;

uniform sampler2D rf;          // RG32F, width = samps, height = N (re, im)
uniform vec4  elems[%(N)d];    // (x, z, nx, nz): position m, outward normal
uniform vec4  viewbox;         // x0, x1, z0, z1 in metres
uniform float c, dly_s, fs;    // sound speed m/s, pulse->rx delay s, sample rate
uniform float samps;           // valid samples per A-scan == texture width
uniform float cos_acc;         // cos(acceptance half-angle)
uniform float apod;            // Tukey fraction, 0 = rect, 1 = full Hann
uniform float t0_s;            // fixed lens/electronic round-trip offset
uniform float alive[%(N)d];    // 0 = dead element, excluded from the sum
uniform float cf_pow;          // coherence-factor exponent, 0 = off

// Half-Hann ramp: 0 at v = 0, 1 at v >= 1, flat slope at both ends so the
// weight has no corner to ring on.
float ramp(float v) { return 0.5 - 0.5 * cos(3.14159265 * clamp(v, 0.0, 1.0)); }

void main() {
    vec2 p = vec2(mix(viewbox.x, viewbox.y, v_uv.x),
                  mix(viewbox.z, viewbox.w, 1.0 - v_uv.y));
    vec2  acc  = vec2(0.0);     // coherent (complex) sum - the image
    float wsum = 0.0;           // sum w         -- the two CF denominators,
    float psum = 0.0;           // sum w |s|^2   -- same weights as acc uses
    float inv_w = 1.0 / samps;
    float a = max(apod, 1e-4);          // a = 0 would divide by zero below
    for (int i = 0; i < %(N)d; i++) {
        if (alive[i] < 0.5) continue;   // dead element: contributes nothing
        vec2 dv = p - elems[i].xy;
        float d = length(dv);
        // tx == rx (monostatic): round trip is 2*d; capture starts dly_s after
        // fire; t0_s is the lens/electronic delay the geometry cannot see
        float t = (2.0 * d / c + t0_s - dly_s) * fs;
        float cosa = dot(dv, elems[i].zw) / max(d, 1e-9);
        if (t >= 0.0 && t <= samps - 1.0 && cosa >= cos_acc) {
            // Index window: v runs 0 at the array centre to 1 at either end,
            // so one ramp handles both ends and stays symmetric under `flip`.
            float v = abs(2.0 * (float(i) / %(Nm1)s) - 1.0);
            float w = ramp((1.0 - v) / a);
            // Angular window: u runs 0 at the acceptance edge to 1 on axis.
            // Tapering the outer `a` of the cone is what stops an element from
            // entering the sum at full weight and stepping the image.
            float u = (cosa - cos_acc) / max(1.0 - cos_acc, 1e-6);
            w *= ramp(u / a);
            vec2 s = texture(rf, vec2((t + 0.5) * inv_w,
                                      (float(i) + 0.5) / %(N)d.0)).rg;
            acc  += w * s;
            wsum += w;
            psum += w * dot(s, s);      // |s|^2 for the analytic sample
        }
    }
    float mag = length(acc);    // envelope of the coherent sum
    if (cf_pow > 0.0) {
        // How much of that sum was actually in phase.  Same weights top and
        // bottom, so a pixel every element agrees on gives 1.0 whatever the
        // taper; Cauchy-Schwarz keeps it inside [0, 1].  wsum == 0 (no element
        // reached this pixel) leaves acc at zero too, so the clamp returns 0.
        float cf = dot(acc, acc) / max(wsum * psum, 1e-20);
        mag *= pow(clamp(cf, 0.0, 1.0), cf_pow);
    }
    f_mag = mag;
}
""" % {"N": N_ELEM, "Nm1": "%.1f" % (N_ELEM - 1)}

# 2x2 max downsample.  Chained to 1x1 so the display pass can read the frame
# peak straight out of a texture - no glReadPixels, no pipeline stall.
REDUCE = """
#version 330
out float f_max;
uniform sampler2D src;
uniform ivec2 srcsz;
void main() {
    ivec2 b = ivec2(gl_FragCoord.xy) * 2;
    float m = 0.0;
    for (int dy = 0; dy < 2; dy++)
        for (int dx = 0; dx < 2; dx++)
            m = max(m, texelFetch(src, min(b + ivec2(dx, dy), srcsz - 1), 0).r);
    f_max = m;
}
"""

COMPRESS = """
#version 330
in vec2 v_uv;
out vec4 f_color;
uniform sampler2D magtex;
uniform sampler2D maxtex;      // 1x1, frame peak
uniform float dyn_db, gain_db, full_scale, auto_gain;
void main() {
    float mag  = texture(magtex, v_uv).r;
    float peak = mix(full_scale, max(texelFetch(maxtex, ivec2(0, 0), 0).r, 1e-9),
                     auto_gain);
    float db = 20.0 * log(mag / peak + 1e-9) / log(10.0);
    float v  = clamp((db + gain_db + dyn_db) / dyn_db, 0.0, 1.0);
    f_color  = vec4(v, v, v, 1.0);
}
"""

#===============================================================================
# GL widget: the B-mode image itself, nothing else
#===============================================================================
class BModeGL(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctx = None
        self.mag_fbo = self.mag_tex = None
        self.reduce = []            # [(fbo, tex, (w, h), (srcw, srch))]
        self.rf_tex = None
        self.tex_samps = 0
        self.tex_gen = -1
        self.elem_key = None         # (geom gen, direction) in the 'elems' uniform
        self.dead_key = None         # dead["gen"] in the 'alive' uniform
        self.fb_w = self.fb_h = 1
        self._screen = None
        self._screen_id = -1
        self._q = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(240, 200)

    # -- setup ----------------------------------------------------------------
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.prog_bf = self.ctx.program(vertex_shader=VERT, fragment_shader=BEAMFORM)
        self.prog_rd = self.ctx.program(vertex_shader=VERT, fragment_shader=REDUCE)
        self.prog_cp = self.ctx.program(vertex_shader=VERT, fragment_shader=COMPRESS)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.vao_bf = self.ctx.vertex_array(self.prog_bf, [(self.vbo, '2f', 'in_pos')])
        self.vao_rd = self.ctx.vertex_array(self.prog_rd, [(self.vbo, '2f', 'in_pos')])
        self.vao_cp = self.ctx.vertex_array(self.prog_cp, [(self.vbo, '2f', 'in_pos')])
        self.prog_bf['elems'].write(elem_uniform().tobytes())
        self.elem_key = (geom["gen"], flip["on"])   # what the uniform holds
        self.prog_bf['alive'].write(alive_mask().tobytes())
        self.dead_key = dead["gen"]
        self.prog_bf['rf'].value = 0
        self.prog_cp['magtex'].value = 0
        self.prog_cp['maxtex'].value = 1
        # full_scale is not constant any more - it tracks the apodization, so
        # _compress sets it per frame rather than once here.

    def _release(self, objs):
        for o in objs:
            try: o.release()
            except Exception: pass

    def _alloc_targets(self, w, h):
        """(Re)build the magnitude buffer and its max-reduction chain."""
        old = [self.mag_fbo, self.mag_tex]
        for fbo, tex, _, _ in self.reduce:
            old += [fbo, tex]
        self.reduce = []
        self.mag_tex = self.ctx.texture((w, h), 1, dtype='f4')
        self.mag_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.mag_tex.repeat_x = self.mag_tex.repeat_y = False
        self.mag_fbo = self.ctx.framebuffer(color_attachments=[self.mag_tex])
        sw, sh = w, h
        while sw > 1 or sh > 1:
            dw, dh = max(1, (sw + 1)//2), max(1, (sh + 1)//2)
            tex = self.ctx.texture((dw, dh), 1, dtype='f4')
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            fbo = self.ctx.framebuffer(color_attachments=[tex])
            self.reduce.append((fbo, tex, (dw, dh), (sw, sh)))
            sw, sh = dw, dh
        self._release([o for o in old if o is not None])

    def resizeGL(self, w, h):
        self.fb_w, self.fb_h = max(1, w), max(1, h)
        self._alloc_targets(self.fb_w, self.fb_h)
        self._screen_id = -1

    # -- the visible slab of tissue ------------------------------------------
    def full_extent(self):
        """(xw, zmax) in metres covering the whole window, at square pixels."""
        zmax = zmax_now()
        return zmax * (self.fb_w / max(1, self.fb_h)), zmax

    def view_box(self):
        """Visible (x0, x1, z0, z1) in metres, clamped inside the full extent.
        Also writes the clamped centre back so panning stops at the edges."""
        xw, zmax = self.full_extent()
        z = min(max(view["zoom"], ZOOM_MIN), ZOOM_MAX)
        w, hgt = xw / z, zmax / z
        cz = view["cz"] if view["cz"] is not None else zmax / 2.0
        cx = min(max(view["cx"], -xw/2 + w/2), xw/2 - w/2)
        cz = min(max(cz, hgt/2), zmax - hgt/2)
        view.update(zoom=z, cx=cx, cz=cz)
        return (cx - w/2, cx + w/2, cz - hgt/2, cz + hgt/2)

    # -- per-frame ------------------------------------------------------------
    def _reset_state(self):
        """QOpenGLWidget hands us the context with its own compositing state
        still set - notably GL_BLEND, which silently eats everything we render
        into the float buffers.  Reset before every batch of passes."""
        self.ctx.enable_only(moderngl.NOTHING)

    def _upload(self):
        """Take whatever the Hilbert worker last published.  Nothing but a
        memcpy to the GPU happens on this thread."""
        with hil_lk:
            if hil["data"] is None or hil["gen"] == self.tex_gen:
                return
            data, samps, gen = hil["data"], hil["samps"], hil["gen"]
        if self.tex_samps != samps or self.rf_tex is None:
            if self.rf_tex is not None:
                self._release([self.rf_tex])
            self.rf_tex = self.ctx.texture((samps, N_ELEM), 2, dtype='f4')
            # LINEAR gives the fractional-delay interpolation; sampling exactly at
            # (i + 0.5)/N in y hits a texel centre, so rows never bleed together
            self.rf_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.rf_tex.repeat_x = self.rf_tex.repeat_y = False
            self.tex_samps = samps
        self.rf_tex.write(data)
        self.tex_gen = gen

    def _beamform(self, fbo, size, vb):
        p = self.prog_bf
        # Re-upload only when the geometry actually changed: 768 bytes, but it
        # is the one uniform that is not a scalar, and the capture path calls
        # this a second time per grab.  The key is (rebuild count, direction) -
        # dragging R or pitch bumps gen, flip just picks the other array.
        key = (geom["gen"], flip["on"])
        if self.elem_key != key:
            p['elems'].write(elem_uniform().tobytes())
            self.elem_key = key
        if self.dead_key != dead["gen"]:            # dead list edited live
            p['alive'].write(alive_mask().tobytes())
            self.dead_key = dead["gen"]
        p['viewbox'].value = (float(vb[0]), float(vb[1]),
                              float(vb[2]), float(vb[3]))
        p['c'].value       = float(state["c"])
        p['dly_s'].value   = float(state["dly_us"]) * 1e-6
        p['fs'].value      = float(FS_HZ)
        p['samps'].value   = float(self.tex_samps)
        p['cos_acc'].value = float(np.cos(np.radians(state["accept"])))
        p['apod'].value    = float(state["apod"])
        p['cf_pow'].value  = float(state["cf"])
        p['t0_s'].value    = float(state["t0_ns"]) * 1e-9
        self.rf_tex.use(0)
        fbo.use()
        fbo.viewport = (0, 0, size[0], size[1])
        self.vao_bf.render(moderngl.TRIANGLE_STRIP)

    def _run_reduce(self):
        src = self.mag_tex
        for fbo, tex, (dw, dh), (sw, sh) in self.reduce:
            src.use(0)
            self.prog_rd['src'].value = 0
            self.prog_rd['srcsz'].value = (sw, sh)
            fbo.use()
            fbo.viewport = (0, 0, dw, dh)
            self.vao_rd.render(moderngl.TRIANGLE_STRIP)
            src = tex

    def _compress(self, magtex, fbo, size):
        magtex.use(0)
        (self.reduce[-1][1] if self.reduce else magtex).use(1)
        self.prog_cp['full_scale'].value = full_scale(state["apod"])
        self.prog_cp['dyn_db'].value    = float(state["dyn"])
        self.prog_cp['gain_db'].value   = float(state["gain"])
        self.prog_cp['auto_gain'].value = 1.0 if state["auto"] else 0.0
        fbo.use()
        fbo.viewport = (0, 0, size[0], size[1])
        self.vao_cp.render(moderngl.TRIANGLE_STRIP)

    def paintGL(self):
        if self.ctx is None or self.mag_fbo is None:
            return
        t0 = time.perf_counter()
        # Always take the newest published generation: while frozen the worker
        # only publishes replay frames, so this is what makes scrubbing work.
        self._upload()
        if self.rf_tex is None:
            return
        self._reset_state()
        vb = self.view_box()
        q = None
        if self._q % 30 == 0:
            q = self.ctx.query(time=True)
            q.__enter__()
        self._beamform(self.mag_fbo, (self.fb_w, self.fb_h), vb)
        self._run_reduce()
        fid = self.defaultFramebufferObject()
        if fid != self._screen_id:
            self._screen = self.ctx.detect_framebuffer(fid)
            self._screen_id = fid
        self._compress(self.mag_tex, self._screen, (self.fb_w, self.fb_h))
        if q is not None:
            q.__exit__(None, None, None)
            perf["gpu_ms"] = q.elapsed / 1e6
        self._q += 1
        perf["cpu_ms"] = (time.perf_counter() - t0) * 1e3

    # -- capture --------------------------------------------------------------
    def grab_bmode(self, scale=CAP_SCALE):
        """Re-render the current view at `scale` x resolution into an offscreen
        FBO and read it back as a QImage.  Same uniforms, so it is exactly the
        on-screen image - including the zoom - just sampled on a finer grid."""
        if self.ctx is None or self.rf_tex is None:
            return None, None
        self.makeCurrent()
        self._reset_state()
        w, h = int(self.fb_w * scale), int(self.fb_h * scale)
        vb = self.view_box()
        mag_t = self.ctx.texture((w, h), 1, dtype='f4')
        mag_t.filter = (moderngl.NEAREST, moderngl.NEAREST)
        mag_f = self.ctx.framebuffer(color_attachments=[mag_t])
        rgb_t = self.ctx.texture((w, h), 4)
        rgb_f = self.ctx.framebuffer(color_attachments=[rgb_t])
        try:
            self._beamform(mag_f, (w, h), vb)
            self._compress(mag_t, rgb_f, (w, h))    # peak from the live chain
            raw = rgb_f.read(components=3, alignment=1)
        finally:
            self._release([mag_f, mag_t, rgb_f, rgb_t])
            self.doneCurrent()
        a = np.frombuffer(raw, np.uint8).reshape(h, w, 3)[::-1]   # GL is bottom-up
        a = np.ascontiguousarray(a)
        return QImage(a.data, w, h, 3*w, QImage.Format_RGB888).copy(), vb

#===============================================================================
# scene painting shared by the live overlay and the captures
#===============================================================================
def sc2px(vb, r, x, z):
    return QPointF(r.left() + (x - vb[0]) / (vb[1] - vb[0]) * r.width(),
                   r.top()  + (z - vb[2]) / (vb[3] - vb[2]) * r.height())

def px2sc(vb, r, px, py):
    if r.width() <= 0 or r.height() <= 0:
        return 0.0, 0.0
    return (vb[0] + (px - r.left()) / r.width()  * (vb[1] - vb[0]),
            vb[2] + (py - r.top())  / r.height() * (vb[3] - vb[2]))

def nice_step(rng):
    for s in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if rng / s <= 10: return s
    return 100

def paint_axes(p, r, vb, s=1.0):
    """Depth (cm) down the left, lateral (cm) along the bottom, array face on
    top.  Ticks follow the visible range, so they get finer as you zoom in."""
    p.save()
    p.setFont(QFont("Consolas", max(6, int(9 * s))))
    fm = QFontMetrics(p.font())
    p.setPen(QPen(QColor(DIM), max(1.0, s)))
    x0, x1, z0, z1 = [v * 100.0 for v in vb]        # cm

    step = nice_step(z1 - z0)                       # left: depth
    v = np.ceil(z0 / step) * step
    while v <= z1 + 1e-9:
        y = r.top() + r.height() * (v - z0) / (z1 - z0)
        p.drawLine(QPointF(r.left() - 5*s, y), QPointF(r.left(), y))
        t = f"{v:g}"
        p.drawText(QPointF(r.left() - 8*s - fm.horizontalAdvance(t),
                           y + fm.ascent()/2 - 1), t)
        v += step
    step = nice_step(x1 - x0)                       # bottom: lateral
    v = np.ceil(x0 / step) * step
    while v <= x1 + 1e-9:
        x = r.left() + r.width() * (v - x0) / (x1 - x0)
        p.drawLine(QPointF(x, r.bottom()), QPointF(x, r.bottom() + 5*s))
        t = f"{v:g}"
        p.drawText(QPointF(x - fm.horizontalAdvance(t)/2,
                           r.bottom() + 7*s + fm.ascent()), t)
        v += step

    p.save()
    p.translate(QPointF(r.left() - 40*s, r.center().y()))
    p.rotate(-90)
    p.drawText(QPointF(-fm.horizontalAdvance("depth (cm)")/2, 0), "depth (cm)")
    p.restore()
    p.drawText(QPointF(r.center().x() - fm.horizontalAdvance("lateral (cm)")/2,
                       r.bottom() + 7*s + 2.2*fm.ascent()), "lateral (cm)")

    if vb[2] <= 0.002:                  # only meaningful when the face is in view
        p.setPen(QPen(QColor("#4db8ff"), max(1.0, s)))
        # column 0 is the element x; read it back from the live table so the
        # ticks follow the R / pitch sliders (EX is local to rebuild_geometry)
        ex = elem_uniform()[:, 0]
        for i in range(N_ELEM):
            x = sc2px(vb, r, ex[i], 0.0).x()
            if r.left() <= x <= r.right():
                p.drawLine(QPointF(x, r.top() - 6*s), QPointF(x, r.top() - 1*s))
    p.setPen(QPen(QColor(FRAME_C), max(1.0, s)))
    p.drawRect(r)
    p.restore()

def meas_mm(m):
    return float(np.hypot(m[2] - m[0], m[3] - m[1]) * 1000.0)

def paint_measures(p, r, vb, measures, s=1.0, hot=None):
    """Calipers: cross at each end, line between, distance label at the midpoint."""
    if not measures:
        return
    p.save()
    p.setClipRect(r)            # a caliper dragged out of view must not spill
                                # over the toolbar / axis gutters
    p.setRenderHint(QPainter.Antialiasing, True)
    font = QFont("Consolas", max(7, int(10 * s)))
    font.setBold(True)
    p.setFont(font)
    fm = QFontMetrics(font)
    arm, hr = 7.0 * s, 4.5 * s

    for i, m in enumerate(measures):
        col = QColor(MEAS_HOT if hot == i else MEAS_C)
        a, b = sc2px(vb, r, m[0], m[1]), sc2px(vb, r, m[2], m[3])
        p.setPen(QPen(QColor(0, 0, 0, 150), 3.0 * s))
        p.drawLine(a, b)
        p.setPen(QPen(col, 1.4 * s))
        p.drawLine(a, b)
        for q in (a, b):
            p.drawLine(QPointF(q.x() - arm, q.y()), QPointF(q.x() + arm, q.y()))
            p.drawLine(QPointF(q.x(), q.y() - arm), QPointF(q.x(), q.y() + arm))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(q, hr, hr)

        txt = f"{meas_mm(m):.1f} mm"
        mid = QPointF((a.x() + b.x())/2, (a.y() + b.y())/2)
        tw, th = fm.horizontalAdvance(txt), fm.height()
        box = QRectF(mid.x() + 8*s, mid.y() - th/2 - 2*s, tw + 8*s, th + 4*s)
        if box.right() > r.right():
            box.moveLeft(mid.x() - 8*s - box.width())
        box.moveLeft(min(max(box.left(), r.left() + 2*s),
                         r.right() - box.width() - 2*s))
        box.moveTop(min(max(box.top(), r.top() + 2*s),
                        r.bottom() - box.height() - 2*s))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 170)))
        p.drawRoundedRect(box, 3*s, 3*s)
        p.setPen(QPen(col))
        p.drawText(QPointF(box.left() + 4*s, box.top() + 2*s + fm.ascent()), txt)
    p.restore()

def paint_mline(p, r, vb, a, b, hot=None, s=1.0):
    """The M-mode line: A at the top of the strip, B at the bottom, ticks along
    it so the strip's vertical axis can be related back to the image."""
    if a is None or b is None:
        return
    p.save()
    p.setClipRect(r)
    p.setRenderHint(QPainter.Antialiasing, True)
    qa, qb = sc2px(vb, r, a[0], a[1]), sc2px(vb, r, b[0], b[1])
    col = QColor(MLINE_C)

    p.setPen(QPen(QColor(0, 0, 0, 150), 3.5 * s))
    p.drawLine(qa, qb)
    p.setPen(QPen(col, 1.6 * s, Qt.DashLine))
    p.drawLine(qa, qb)

    # quarter ticks: a coarse ruler tying strip rows back to the image
    p.setPen(QPen(col, 1.2 * s))
    dx, dy = qb.x() - qa.x(), qb.y() - qa.y()
    L = float(np.hypot(dx, dy)) or 1.0
    nx, ny = -dy / L * 4.0 * s, dx / L * 4.0 * s
    for k in (0.25, 0.5, 0.75):
        m = QPointF(qa.x() + dx * k, qa.y() + dy * k)
        p.drawLine(QPointF(m.x() - nx, m.y() - ny), QPointF(m.x() + nx, m.y() + ny))

    font = QFont("Consolas", max(7, int(9 * s)))
    font.setBold(True)
    p.setFont(font)
    for q, t, w in ((qa, "A", 0), (qb, "B", 1)):
        p.setBrush(QBrush(QColor(col if hot == w else Qt.black)))
        p.setPen(QPen(col, 1.4 * s))
        p.drawEllipse(q, 5.0 * s, 5.0 * s)
        p.setPen(QPen(col))
        p.drawText(QPointF(q.x() + 7 * s, q.y() - 5 * s), t)
    p.restore()

#===============================================================================
# measurement interaction, shared by the live overlay and the capture viewer
#===============================================================================
HIT = 10.0          # grab radius, px

def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L = dx*dx + dy*dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px-x0)*dx + (py-y0)*dy) / L))
    return np.hypot(px - (x0 + t*dx), py - (y0 + t*dy))

class MeasureCanvas(QWidget):
    """Mouse handling for calipers.  Subclasses supply image_rect() and the
    view box; endpoints are kept in metres so they survive zoom, pan, resize,
    depth changes and being re-rendered into a capture at another resolution."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.measures = []          # [x0, z0, x1, z1] in metres
        self.vb = (-0.05, 0.05, 0.0, 0.08)
        self._drag = None           # (index, which)  which: 0, 1 or 2 (=whole line)
        self._off = None
        self._new = False
        self.hot = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def image_rect(self):
        raise NotImplementedError

    def _pick(self, pt):
        """-> (index, which) for the nearest grabbable thing, or None."""
        r = self.image_rect()
        best = None
        for i, m in enumerate(self.measures):
            for w, (x, z) in enumerate(((m[0], m[1]), (m[2], m[3]))):
                q = sc2px(self.vb, r, x, z)
                d = np.hypot(pt.x() - q.x(), pt.y() - q.y())
                if d <= HIT and (best is None or d < best[0]):
                    best = (d, i, w)
        if best:
            return best[1], best[2]
        for i, m in enumerate(self.measures):
            a = sc2px(self.vb, r, m[0], m[1])
            b = sc2px(self.vb, r, m[2], m[3])
            if seg_dist(pt.x(), pt.y(), a.x(), a.y(), b.x(), b.y()) <= HIT:
                return i, 2
        return None

    # -- events ---------------------------------------------------------------
    def mousePressEvent(self, ev):
        pt = ev.position()
        hit = self._pick(pt)
        if ev.button() == Qt.RightButton:
            if hit:
                self.measures.pop(hit[0])
                self.hot = None
                self.update(); self.changed.emit()
            return
        if ev.button() != Qt.LeftButton:
            return
        if not self.image_rect().contains(pt) and not hit:
            return
        if hit:
            i, w = hit
            self._drag, self._new = (i, w), False
            if w == 2:
                x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
                m = self.measures[i]
                self._off = (m[0]-x, m[1]-z, m[2]-x, m[3]-z)
        else:
            x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
            self.measures.append([x, z, x, z])
            self._drag, self._new = (len(self.measures)-1, 1), True
        self.hot = self._drag[0]
        self.update(); self.changed.emit()

    def mouseMoveEvent(self, ev):
        pt = ev.position()
        if self._drag is None:
            hit = self._pick(pt)
            hot = hit[0] if hit else None
            self.setCursor(Qt.SizeAllCursor if hit and hit[1] == 2 else
                           (Qt.PointingHandCursor if hit else Qt.CrossCursor))
            if hot != self.hot:
                self.hot = hot
                self.update()
            return
        i, w = self._drag
        x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
        m = self.measures[i]
        if w == 2:
            m[0], m[1] = x + self._off[0], z + self._off[1]
            m[2], m[3] = x + self._off[2], z + self._off[3]
        else:
            m[2*w], m[2*w+1] = x, z
        self.update(); self.changed.emit()

    def mouseReleaseEvent(self, ev):
        if self._drag is None:
            return
        i, _ = self._drag
        m = self.measures[i]
        r = self.image_rect()
        a, b = sc2px(self.vb, r, m[0], m[1]), sc2px(self.vb, r, m[2], m[3])
        if self._new and np.hypot(a.x()-b.x(), a.y()-b.y()) < 4.0:
            self.measures.pop(i)            # a plain click, not a drag
            self.hot = None
        self._drag, self._new = None, False
        self.update(); self.changed.emit()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.measures:
            self.measures.pop(self.hot if self.hot is not None else -1)
            self.hot = None
            self.update(); self.changed.emit()
        else:
            super().keyPressEvent(ev)

    def clear_measures(self):
        self.measures.clear()
        self.hot = None
        self.update(); self.changed.emit()

#===============================================================================
# live scene: GL image + transparent overlay for axes, calipers and zoom
#===============================================================================
class LiveOverlay(MeasureCanvas):
    """Transparent child sitting on the GL widget.  Owns zoom/pan because it is
    the thing receiving the mouse; the GL widget reads the resulting view box."""
    zoomed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pan = None
        self._mdrag = None          # 0 = end A, 1 = end B, 2 = whole line
        self._moff = None
        self._mhot = None

    def image_rect(self):
        return QRectF(ML, MT, max(1, self.width() - ML - MR),
                      max(1, self.height() - MT - MB))

    # -- M-line ---------------------------------------------------------------
    # Only live while the M-mode box is ticked, and it takes priority over
    # caliper CREATION but not over grabbing a caliper that is already there -
    # so an existing measurement stays draggable and the M-line gets the empty
    # space.  Ctrl is left alone: that is pan.
    def _pick_mline(self, pt):
        if not mline["on"] or mline["a"] is None:
            return None
        r = self.image_rect()
        qa = sc2px(self.vb, r, *mline["a"])
        qb = sc2px(self.vb, r, *mline["b"])
        for w, q in ((0, qa), (1, qb)):
            if np.hypot(pt.x() - q.x(), pt.y() - q.y()) <= HIT:
                return w
        if seg_dist(pt.x(), pt.y(), qa.x(), qa.y(), qb.x(), qb.y()) <= HIT:
            return 2
        return None

    # -- zoom / pan -----------------------------------------------------------
    def wheelEvent(self, ev):
        r = self.image_rect()
        pt = ev.position()
        if not r.contains(pt):
            return
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        old = view["zoom"]
        new = min(max(old * (1.25 ** steps), ZOOM_MIN), ZOOM_MAX)
        if new == old:
            return
        # keep the tissue under the cursor pinned while the box shrinks/grows
        x, z = px2sc(self.vb, r, pt.x(), pt.y())
        fx = (pt.x() - r.left()) / r.width()
        fy = (pt.y() - r.top()) / r.height()
        w  = (self.vb[1] - self.vb[0]) * old / new
        hg = (self.vb[3] - self.vb[2]) * old / new
        view.update(zoom=new, cx=x - (fx - 0.5) * w, cz=z - (fy - 0.5) * hg)
        self.zoomed.emit()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or \
           (ev.button() == Qt.LeftButton and ev.modifiers() & Qt.ControlModifier):
            self._pan = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if mline["on"] and ev.button() == Qt.LeftButton:
            pt  = ev.position()
            hit = self._pick_mline(pt)
            if hit is not None:
                self._mdrag = hit
                if hit == 2:
                    x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
                    self._moff = (mline["a"][0] - x, mline["a"][1] - z,
                                  mline["b"][0] - x, mline["b"][1] - z)
                self.update()
                return
            if self.image_rect().contains(pt) and not self._pick(pt):
                x, z = px2sc(self.vb, self.image_rect(), pt.x(), pt.y())
                mline["a"] = mline["b"] = (x, z)
                self._mdrag = 1
                self.update()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._mdrag is not None:
            x, z = px2sc(self.vb, self.image_rect(),
                         ev.position().x(), ev.position().y())
            if self._mdrag == 2:
                mline["a"] = (x + self._moff[0], z + self._moff[1])
                mline["b"] = (x + self._moff[2], z + self._moff[3])
            else:
                mline["a" if self._mdrag == 0 else "b"] = (x, z)
            self.update()
            return
        if self._pan is not None:
            r = self.image_rect()
            x0, z0 = px2sc(self.vb, r, self._pan.x(), self._pan.y())
            x1, z1 = px2sc(self.vb, r, ev.position().x(), ev.position().y())
            view["cx"] += x0 - x1
            view["cz"] = (view["cz"] or 0.0) + z0 - z1
            self._pan = ev.position()
            self.zoomed.emit()
            return
        if mline["on"]:
            hot = self._pick_mline(ev.position())
            if hot != self._mhot:
                self._mhot = hot
                self.update()
            if hot is not None:
                self.setCursor(Qt.SizeAllCursor if hot == 2
                               else Qt.PointingHandCursor)
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._mdrag is not None:
            r = self.image_rect()
            qa = sc2px(self.vb, r, *mline["a"])
            qb = sc2px(self.vb, r, *mline["b"])
            if np.hypot(qa.x() - qb.x(), qa.y() - qb.y()) < 4.0:
                mline["a"] = mline["b"] = None      # a click, not a drag
            self._mdrag, self._moff = None, None
            # The history described the OLD line, so it is not comparable to
            # what comes next - start the strip again rather than splice.
            mm_reset()
            self.update()
            return
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.CrossCursor)
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self._pick(ev.position()):
            reset_view()
            self.zoomed.emit()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.image_rect()
        paint_axes(p, r, self.vb, 1.0)
        paint_measures(p, r, self.vb, self.measures, 1.0, self.hot)
        if mline["on"]:
            paint_mline(p, r, self.vb, mline["a"], mline["b"], self._mhot)
        p.end()

class Scene(QWidget):
    """Container: paints the background, sizes the GL widget inside the axis
    gutters, and keeps a transparent overlay on top of it."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"background:{PLOT_BG};")
        self.gl = BModeGL(self)
        self.ov = LiveOverlay(self)
        self.ov.raise_()
        self.ov.zoomed.connect(self.gl.update)
        self.setMinimumSize(420, 340)

    def resizeEvent(self, ev):
        w, h = self.width(), self.height()
        self.gl.setGeometry(ML, MT, max(1, w - ML - MR), max(1, h - MT - MB))
        self.ov.setGeometry(0, 0, w, h)

    def sync_view(self):
        self.ov.vb = self.gl.view_box()

#===============================================================================
# captures
#===============================================================================
class Capture:
    _n = 0
    def __init__(self, img, vb, measures, info):
        Capture._n += 1
        self.n = Capture._n
        self.img, self.vb = img, vb
        self.measures = [list(m) for m in measures]
        self.info = info
        self.stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.file_stamp = time.strftime("%Y%m%d_%H%M%S")
        self.thumb_label = None

def render_capture(cap, with_measures=True, s=CAP_SCALE):
    """Compose a standalone still: B-mode + axes + footer (+ calipers)."""
    iw, ih = cap.img.width(), cap.img.height()
    ml, mt, mr, mb = int(ML*s), int(MT*s), int(MR*s), int(MB*s)
    foot = int(20 * s)
    out = QImage(iw + ml + mr, ih + mt + mb + foot, QImage.Format_RGB32)
    out.fill(QColor(PLOT_BG))
    p = QPainter(out)
    r = QRectF(ml, mt, iw, ih)
    p.drawImage(QPointF(ml, mt), cap.img)
    paint_axes(p, r, cap.vb, s)
    if with_measures:
        paint_measures(p, r, cap.vb, cap.measures, s)
    p.setFont(QFont("Consolas", max(6, int(8 * s))))
    p.setPen(QPen(QColor(DIM)))
    fm = QFontMetrics(p.font())
    p.drawText(QPointF(ml, mt + ih + mb + (foot + fm.ascent()) / 2),
               f"#{cap.n}  {cap.stamp}   {cap.info}")     # in the footer band,
                                                          # clear of the axis text
    p.end()
    return out

class CaptureView(MeasureCanvas):
    """A still, scaled to fit, with the same caliper interaction as the live
    view.  Wheel/drag here zoom the bitmap (the beamformer is not re-run), which
    is what you want for placing calipers precisely on a frozen image."""
    def __init__(self, cap, parent=None):
        super().__init__(parent)
        self.cap = cap
        self.base = render_capture(cap, with_measures=False)
        self.measures = cap.measures            # edit in place
        self.vb = cap.vb
        self._rect = QRectF(0, 0, 1, 1)
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._grab = None
        self.setMinimumSize(520, 420)
        self.setFocusPolicy(Qt.StrongFocus)

    def _dst(self):
        bw, bh = self.base.width(), self.base.height()
        k = min(self.width() / bw, self.height() / bh) * self.zoom
        w, h = bw * k, bh * k
        return QRectF((self.width()-w)/2 + self.pan.x(),
                      (self.height()-h)/2 + self.pan.y(), w, h), k

    def image_rect(self):
        return self._rect

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if steps:
            before = ev.position() - self._dst()[0].topLeft()
            self.zoom = min(max(self.zoom * (1.25 ** steps), 1.0), 16.0)
            after = ev.position() - self._dst()[0].topLeft()
            self.pan += after - before      # keep the point under the cursor
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or \
           (ev.button() == Qt.LeftButton and ev.modifiers() & Qt.ControlModifier):
            self._grab = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._grab is not None:
            self.pan += ev.position() - self._grab
            self._grab = ev.position()
            self.update()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._grab is not None:
            self._grab = None
            self.setCursor(Qt.CrossCursor)
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if not self._pick(ev.position()):
            self.zoom, self.pan = 1.0, QPointF(0, 0)
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        dst, k = self._dst()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(dst, self.base)
        # where the B-mode sub-rect landed inside the scaled composite
        self._rect = QRectF(dst.left() + ML*CAP_SCALE*k, dst.top() + MT*CAP_SCALE*k,
                            self.cap.img.width()*k, self.cap.img.height()*k)
        paint_measures(p, self._rect, self.vb, self.measures,
                       max(0.8, k * CAP_SCALE), self.hot)
        p.end()

class ReverbPlot(QWidget):
    """Two stacked panels: the mean range profile, and its autocorrelation.

    The profile is there so a peak can be checked by eye - real reverberation
    shows as evenly spaced bands in the top panel at the spacing the bottom
    panel calls out, and if they are not visible up there the peak is not
    reverberation however tall it is."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.setMinimumSize(560, 380)

    def _axes(self, p, r, title):
        p.fillRect(r, QColor(PLOT_BG))
        p.setPen(QPen(QColor(FRAME_C))); p.drawRect(r)
        p.setPen(QPen(QColor(DIM))); p.setFont(QFont("Consolas", 8))
        p.drawText(r.adjusted(6, 3, -6, 0), Qt.AlignLeft | Qt.AlignTop, title)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        d = self.data
        w, h = self.width(), self.height()
        top = QRectF(8, 8, w - 16, h * 0.42 - 12)
        bot = QRectF(8, h * 0.42 + 4, w - 16, h * 0.58 - 12)
        if d is None:
            self._axes(p, top, "range profile")
            self._axes(p, bot, "autocorrelation")
            p.setPen(QPen(QColor(DIM)))
            p.drawText(self.rect(), Qt.AlignCenter, "waiting for a sweep…")
            p.end(); return

        # -- range profile, dB vs depth ---------------------------------------
        self._axes(p, top, f"mean range profile, {d['lines']} radial lines "
                           f"({d['z0_mm']:.0f}–{d['z1_mm']:.0f} mm)")
        y = d["prof"]
        y0, y1 = float(y.min()), float(y.max())
        rng = max(y1 - y0, 1e-6)
        pts = [QPointF(top.left() + top.width() * i / (y.size - 1),
                       top.bottom() - (top.height() - 18) * (y[i] - y0) / rng - 4)
               for i in range(y.size)]
        p.setPen(QPen(QColor(MEAS_C), 1)); p.drawPolyline(QPolygonF(pts))
        # Mark the harmonics of the strongest period, so the eye can check them
        # against the bands rather than taking the autocorrelation on trust.
        if d["peaks"]:
            L = d["peaks"][0][0]
            span = d["z1_mm"] - d["z0_mm"]
            p.setPen(QPen(QColor(OK_C), 1, Qt.DashLine))
            k = 1
            while k * L < span:
                x = top.left() + top.width() * (k * L) / span
                p.drawLine(QPointF(x, top.top() + 14), QPointF(x, top.bottom()))
                k += 1

        # -- autocorrelation ---------------------------------------------------
        self._axes(p, bot, "autocorrelation of the detrended dB profile")
        a, lag = d["acc"], d["lag_mm"]
        lo, hi = d["lo"], d["hi"]
        seg, ls = a[lo:hi], lag[lo:hi]
        if seg.size > 2:
            amax = max(float(np.abs(seg).max()), 1e-6)
            def X(v): return bot.left() + bot.width() * (v - ls[0]) / max(ls[-1] - ls[0], 1e-9)
            def Y(v): return bot.center().y() + 10 - (bot.height() * 0.36) * v / amax
            p.setPen(QPen(QColor(FRAME_C), 1))
            p.drawLine(QPointF(bot.left(), Y(0)), QPointF(bot.right(), Y(0)))
            pts = [QPointF(X(ls[i]), Y(seg[i])) for i in range(seg.size)]
            p.setPen(QPen(QColor(MLINE_C), 1)); p.drawPolyline(QPolygonF(pts))
            p.setFont(QFont("Consolas", 8))
            for j, (L, v, z) in enumerate(d["peaks"]):
                if not (ls[0] <= L <= ls[-1]):
                    continue
                col = QColor(WARN_C if j == 0 else DIM)
                p.setPen(QPen(col, 1))
                p.drawLine(QPointF(X(L), Y(0)), QPointF(X(L), Y(v)))
                p.drawText(QPointF(X(L) + 3, Y(v) - 3), f"{L:.1f} mm  {z:.1f}o")
            p.setPen(QPen(QColor(DIM)))
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                mm = ls[0] + frac * (ls[-1] - ls[0])
                p.drawText(QPointF(X(mm) - 12, bot.bottom() - 3), f"{mm:.0f}")
        p.end()

class ReverbDialog(QDialog):
    """Live reverberation scan.  Non-modal and self-refreshing so it can sit
    open while the probe is moved - which is how you use it: a real multiple
    tracks the layer spacing as you press, speckle does not."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("reverberation scan")
        self.setStyleSheet(parent.styleSheet() if parent else "")
        v = QVBoxLayout(self); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        self.plot = ReverbPlot(self); v.addWidget(self.plot, 1)
        self.lbl = QLabel(""); self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet(f"color:{DIM};")
        v.addWidget(self.lbl)
        self.t = QTimer(self); self.t.timeout.connect(self.refresh)
        self.t.start(400)                   # 2.5 Hz: a scan is ~55 ms
        self.resize(660, 460)
        self.refresh()

    def refresh(self):
        if not self.isVisible():
            return
        with hil_lk:
            an, samps = hil["data"], hil["samps"]
        try:
            d = reverb_scan(an, samps)
        except Exception as e:                  # never let a diagnostic crash
            self.lbl.setText(f"scan failed: {e}")   # the app it is diagnosing
            return
        self.plot.data = d
        self.plot.update()
        if d is None:
            self.lbl.setText("no sweep to analyse yet.")
            return
        if not d["peaks"]:
            # Deliberately not "the image is clean".  Calibration says this test
            # misses a -9 dB/bounce multiple ~90% of the time, so a null is weak
            # evidence and saying otherwise would send him down the wrong path.
            self.lbl.setText(
                f"No periodic structure above {RVB_Z_REPORT:.1f} sigma.\n"
                "This test is specific but NOT sensitive - it only reliably "
                "catches strong multiples, so this does not rule reverberation "
                "out. It does mean reverb is unlikely to be the DOMINANT term, "
                "so weigh grating lobes (lower f0), wall aberration (raise "
                "coh), and sweep-time motion (hold your breath) first.")
            self.lbl.setStyleSheet(f"color:{DIM};")
            return
        L, v, z = d["peaks"][0]
        rest = ("  also " + ", ".join(f"{q[0]:.1f} mm" for q in d["peaks"][1:])
                if len(d["peaks"]) > 1 else "")
        harm = [q[0] for q in d["peaks"][1:] if abs(q[0] - 2*L) < 0.15 * L]
        strong = z >= RVB_Z_STRONG
        self.lbl.setText(
            f"{'STRONG' if strong else 'Suggestive'}: period {L:.1f} mm "
            f"({z:.1f} sigma).{rest}\n"
            + ("A 2x harmonic is present too, which is what a genuine multiple "
               "looks like. " if harm else
               "No 2x harmonic, so this could equally be layered anatomy. ")
            + "Confirm it before believing it: the dashed marks above should "
              "land on real bands, and a 2-3 cm water or gel standoff should "
              "CHANGE the spacing - a probe-face multiple moves with the "
              "standoff, tissue structure does not.")
        self.lbl.setStyleSheet(f"color:{WARN_C if strong else FG};")

    def closeEvent(self, ev):
        self.t.stop()
        super().closeEvent(ev)

class CaptureDialog(QDialog):
    def __init__(self, cap, on_change, parent=None):
        super().__init__(parent)
        self.cap, self.on_change = cap, on_change
        self.setWindowTitle(f"capture #{cap.n} - {cap.stamp}")
        self.setStyleSheet(APP_QSS)
        v = QVBoxLayout(self); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)
        self.view = CaptureView(cap, self)
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        hint = QLabel("drag to measure · drag ends or the middle to adjust · "
                      "right-click a line to delete · wheel zooms, ctrl-drag pans")
        hint.setStyleSheet(f"color:{DIM};")
        row.addWidget(hint); row.addStretch(1)
        b_clr = QPushButton("clear measurements"); b_clr.clicked.connect(self._clear)
        b_sav = QPushButton("save PNG…");          b_sav.clicked.connect(self._save)
        b_cls = QPushButton("close");              b_cls.clicked.connect(self.close)
        for b in (b_clr, b_sav, b_cls): row.addWidget(b)
        v.addLayout(row)
        self.view.changed.connect(self._touched)
        self.resize(900, 780)

    def _touched(self):
        self.cap.measures = self.view.measures
        self.on_change(self.cap)

    def _clear(self):
        self.view.clear_measures()

    def _save(self):
        save_capture(self.cap, self)

def save_capture(cap, parent):
    path, _ = QFileDialog.getSaveFileName(
        parent, "save B-mode capture",
        os.path.join(os.path.expanduser("~"), "Pictures",
                     f"bmode_{cap.file_stamp}_{cap.n:03d}.png"),
        "PNG image (*.png)")
    if not path:
        return
    if render_capture(cap).save(path, "PNG"):
        print(f"saved {path}")
    else:
        print(f"FAILED to save {path}")

#===============================================================================
# settings snapshot
#===============================================================================
# A capture is a picture; this is the machine that made it.  Every control on
# this window ends up in one JSON file, next to a PNG of what was on screen when
# the button was pressed, so a session can be reconstructed - or explained -
# after the fact without having to remember where forty sliders were sitting.
#
# Two things are written on every press:
#
#   settings/latest.json  - overwritten, so "what is it set to right now" is
#                           always one fixed path
#   settings/<stamp>.json - kept, so the history of an evening is walkable
#
# ...plus the matching PNG beside each.  The values are the LIVE state, not the
# slider positions: band edges are clamped to Nyquist, the averager reports how
# many sweeps it actually holds, and the level meters and jitter numbers are
# measurements of the last sweep.  That is deliberate - the point is to record
# what the image really was, and a slider that is fighting a clamp is exactly
# the sort of thing worth catching later.
SETTINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings")

def _plain(o):
    """json fallback: numpy scalars/arrays and sets are all over this file."""
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)

def settings_snapshot(main, note=""):
    lo, hi = band_edges()
    gl = main.scene.gl
    n_cine, cine_s, cine_mb = cine.status()
    return {
        "saved":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "note":    note,
        "host":    os.path.basename(__file__),
        "source":  "hardware" if HW else "simulation",
        "argv":    sys.argv[1:],
        # The same one-liner that footers a capture, so a settings file and a
        # saved PNG can be matched up by eye.
        "summary": main.info_line(),

        # -- what the FPGA was told to do ------------------------------------
        "acquisition": {
            "depth_cm":     state["depth_cm"],
            "win_words":    cfg["win_words"],
            "win_samples":  cfg["samps"],
            "win_us":       round(cfg["win_us"], 2),
            "dly_us":       state["dly_us"],      # pulse -> receive settling
            "damp_gap_us":  main.gap,             # receive end -> next pulse
            "tgc_min":      main.tgc_lo,
            "tgc_max":      max(main.tgc_lo, main.tgc_hi),
            "fs_hz":        FS_HZ,
            "n_elem_rx":    N_ELEM,
        },
        "transmit": {
            "armed":         pulser.arm,
            "chirp_on":      pulser.chirp_on,
            "chirp_f0_mhz":  pulser.chirp_f0_mhz,
            "chirp_f1_mhz":  pulser.chirp_f1_mhz,
            "chirp_us":      pulser.chirp_us,
            "n_cycles":      pulser.n_cycles,
            "t_drive_ns":    pulser.t_drive_ns,
            "t_dead_ns":     pulser.t_dead_ns,
            "t_settle_us":   pulser.t_settle_us,
            "t_inhib_us":    pulser.t_inhib_us,
            "t_ring_us":     pulser.t_ring_us,
            "t_rx_us":       pulser.t_rx_us,      # driven by depth, not a slider
            "n_elem":        pulser.n_elem,
            "single_elem":   pulser.single_elem,  # None = walk the aperture
            "f0_mhz":        round(pulser.f0_hz() / 1e6, 3),
            "burst_us":      round(pulser.burst_ns() / 1e3, 3),
            "element_period_us": round(pulser.element_period_us(), 2),
            "frame_ms":      round(pulser.frame_ms(), 3),
        },

        # -- CPU side: works on replayed cine exactly as it does live ---------
        "receive": {
            "bandpass_on":   state["band_on"],
            "band_f0_mhz":   state["band_f0"],
            "band_bw_mhz":   state["band_bw"],
            "band_lo_mhz":   round(lo / 1e6, 3),  # after the Nyquist clamp
            "band_hi_mhz":   round(hi / 1e6, 3),
            "avg_sweeps":    rf_avg.n,
            "avg_held":      rf_avg.depth(),      # < avg_sweeps while filling
            "matched_filter": state["mf"],
            "dejitter_on":   state["jit"],
            "jitter_rms_ns": round(jit["rms_ns"], 2),
            "jitter_pp_ns":  round(jit["pp_ns"], 2),
            "jitter_used":   jit["used"],
            "jitter_railed": jit["railed"],
            "bg_subtract":   bg["on"],
            "bg_ref":        bg["ref"] is not None,
            "near_dbfs":     round(level["near"], 2),   # clipping meter
            "far_dbfs":      round(level["far"], 2),
        },
        "beamformer": {
            "c_m_s":        state["c"],
            "apod":         state["apod"],
            "cf":           state["cf"],
            "accept_deg":   state["accept"],
            "t0_ns":        state["t0_ns"],
            "R_mm":         geom["R_mm"],
            "pitch_mm":     geom["pitch_mm"],
            "aperture_mm":  round(APERTURE_MM, 3),
            "flip_lr":      flip["on"],
            "dead":         sorted(dead["set"]),
            "alive":        n_alive(),
        },
        "display": {
            "dyn_db":     state["dyn"],
            "gain_db":    state["gain"],
            "auto_gain":  state["auto"],
            "signed":     mode["signed"],
            "zoom":       round(view["zoom"], 3),
            "pan_cx":     view["cx"],
            "pan_cz":     view["cz"],
            "grid":       [gl.fb_w, gl.fb_h],
            "mmode_on":   mline["on"],
            # metres, like the calipers, so they stay on the tissue
            "mline_a":    mline["a"],
            "mline_b":    mline["b"],
            "measurements_mm": [round(meas_mm(m), 2)
                                for m in main.scene.ov.measures],
        },
        "stream": {
            "frozen":       state["frozen"],
            "mbps":         round(stats["mbps"], 1),
            "sweeps_per_s": round(stats["fps"] / N_ELEM, 1),
            "frames":       stats["frames"],
            "drops":        stats["drops"],
            "resyncs":      stats["resyncs"],
            "holes":        [stats["seq_bad"], stats["seq_chk"]],
            "skips":        stats["skips"],
            "cine_frames":  n_cine,
            "cine_seconds": round(cine_s, 2),
            # where the play head is when frozen: negative = seconds back from
            # live, which is the only thing that says WHICH frame this describes
            "cine_offset_s": (round(main.play_t - main._span(), 3)
                              if state["frozen"] and main.review else None),
        },
    }

def write_settings(main, note=""):
    """Write latest.json + a stamped copy, each with the current image beside
    it.  Returns the stamped json path, or None if nothing could be written."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    snap  = settings_snapshot(main, note)
    snap["image"] = None
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        # The PNG is best-effort: no GL context yet (or a stream that never
        # started) must not cost the settings file, which is the point of the
        # button.  Rendered through the capture path so it carries axes and the
        # info footer, i.e. it is readable on its own.
        img, vb = main.scene.gl.grab_bmode()
        if img is not None:
            cap = Capture(img, vb, main.scene.ov.measures, snap["summary"])
            Capture._n -= 1                 # a snapshot is not a numbered capture
            shot = render_capture(cap)
            if shot.save(os.path.join(SETTINGS_DIR, f"{stamp}.png"), "PNG"):
                snap["image"] = f"{stamp}.png"
                shot.save(os.path.join(SETTINGS_DIR, "latest.png"), "PNG")
        for name in (f"{stamp}.json", "latest.json"):
            with open(os.path.join(SETTINGS_DIR, name), "w") as f:
                json.dump(snap, f, indent=2, default=_plain)
    except OSError as e:
        print(f"FAILED to save settings: {e}")
        return None
    path = os.path.join(SETTINGS_DIR, f"{stamp}.json")
    print(f"saved settings {path}")
    return path

class ThumbLabel(QLabel):
    clicked = Signal()
    removed = Signal()
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        elif ev.button() == Qt.RightButton:
            self.removed.emit()

#===============================================================================
# controls
#===============================================================================
APP_QSS = f"""
QWidget {{ background:{BG}; color:{FG}; font-family:Consolas; font-size:11px; }}
QLabel  {{ background:transparent; }}
QPushButton {{ background:#1a2129; border:1px solid #2c3a45; padding:4px 9px;
              border-radius:3px; }}
QPushButton:hover  {{ background:#22303a; }}
QPushButton:pressed{{ background:#2c3f4c; }}
QPushButton:checked{{ background:#8a3a1e; border-color:#c25a2c; color:#ffe; }}
QPushButton:disabled {{ color:#3d4a55; border-color:#1e262e; }}
QPushButton:checked:disabled {{ background:#33221a; border-color:#4a3226; }}
QCheckBox {{ spacing:4px; }}
QSlider::groove:horizontal {{ height:3px; background:#2a3540; border-radius:2px; }}
QSlider::handle:horizontal {{ width:10px; margin:-5px 0; border-radius:5px;
                              background:#6fa8c9; }}
QSlider::sub-page:horizontal {{ background:#3d6c88; border-radius:2px; }}
QScrollArea {{ border:1px solid #22303a; }}
QFrame#panel {{ border:1px solid #22303a; border-radius:3px; }}
"""

def mkslider(row, label, lo, hi, val, on_change=None, on_release=None,
             width=104, unit=""):
    box = QWidget()
    l = QHBoxLayout(box); l.setContentsMargins(5, 0, 5, 0); l.setSpacing(4)
    lab = QLabel(label); lab.setStyleSheet(f"color:{DIM};")
    s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(val)
    s.setFixedWidth(width)
    vl = QLabel(f"{val}{unit}"); vl.setFixedWidth(42)
    vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    def _ch(v):
        vl.setText(f"{v}{unit}")
        if on_change: on_change(v)
    s.valueChanged.connect(_ch)
    if on_release:
        s.sliderReleased.connect(lambda: on_release(s.value()))
    l.addWidget(lab); l.addWidget(s); l.addWidget(vl)
    row.addWidget(box)
    return s

def mkfslider(row, label, lo, hi, step, val, on_change, width=104, unit="",
              fmt="%g", tip=None, quant=None):
    """Float slider.  QSlider only counts integers, so it counts in `step` units
    and the real value is position * step.

    `quant`, if given, maps a value to whatever the hardware actually resolves
    (FPGA clock cycles, for the pulser fields).  A drag then emits a command
    only when the QUANTISED value changes, so sweeping across a range worth one
    cycle sends one command rather than fifty.  Pure-shader sliders leave it
    None and fire on every step.
    """
    box = QWidget()
    l = QHBoxLayout(box); l.setContentsMargins(5, 0, 5, 0); l.setSpacing(4)
    lab = QLabel(label); lab.setStyleSheet(f"color:{DIM};")
    s = QSlider(Qt.Horizontal)
    s.setRange(int(round(lo / step)), int(round(hi / step)))
    s.setValue(int(round(val / step)))
    s.setFixedWidth(width)
    vl = QLabel(f"{fmt % val}{unit}"); vl.setFixedWidth(46)
    vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    last = {"q": quant(val) if quant else None}
    def _ch(pos):
        v = pos * step
        vl.setText(f"{fmt % v}{unit}")
        if quant is not None:
            q = quant(v)
            if q == last["q"]:
                return                  # same clock-cycle value - nothing to send
            last["q"] = q
        on_change(v)
    s.valueChanged.connect(_ch)
    if tip:
        for w in (s, lab, vl):
            w.setToolTip(tip)
    l.addWidget(lab); l.addWidget(s); l.addWidget(vl)
    row.addWidget(box)
    return s

#===============================================================================
# cine transport: play/step/repeat buttons, scrub timeline, speed knob
#===============================================================================
class GlyphButton(QPushButton):
    """Transport button that paints its own icon, so the look never depends on
    the monospace font happening to carry play/pause/loop glyphs.  The frame,
    hover and checked states still come from the app stylesheet."""
    def __init__(self, kind, tip="", checkable=False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setCheckable(checkable)
        self.setToolTip(tip)
        self.setFixedSize(32, 26)

    def set_kind(self, kind):
        self._kind = kind
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor("#3d4a55") if not self.isEnabled() else \
              QColor("#ffeedd" if self.isChecked() else FG)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        k = self._kind
        if k == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - 4, cy - 6), QPointF(cx - 4, cy + 6),
                                     QPointF(cx + 6, cy)]))
        elif k == "pause":
            p.drawRect(QRectF(cx - 5.2, cy - 6, 3.4, 12))
            p.drawRect(QRectF(cx + 1.8, cy - 6, 3.4, 12))
        elif k in ("step-", "step+"):
            s = -1.0 if k == "step-" else 1.0
            p.drawPolygon(QPolygonF([QPointF(cx - 3*s, cy - 6), QPointF(cx - 3*s, cy + 6),
                                     QPointF(cx + 4*s, cy)]))
            p.drawRect(QRectF(cx + (4 if s > 0 else -6), cy - 6, 2.0, 12))
        elif k == "repeat":
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 1.7))
            p.drawArc(QRectF(cx - 7, cy - 6, 14, 12), 35*16, 290*16)
            a  = np.radians(35.0)
            tp = QPointF(cx + 7*np.cos(a), cy - 6*np.sin(a))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(col))
            p.drawPolygon(QPolygonF([tp + QPointF(-3.6, -2.4), tp + QPointF(3.2, -1.0),
                                     tp + QPointF(-0.6, 3.6)]))
        p.end()

class Knob(QWidget):
    """Log-scaled rotary control: drag up/down or wheel to change, double-click
    to snap back to the detent.  Log scaling is what makes 0.1x and 4x equally
    reachable from 1x, which a linear slider cannot do."""
    changed = Signal(float)

    def __init__(self, lo, hi, val, detent=1.0, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.detent = float(lo), float(hi), float(detent)
        self.val = float(val)
        self._y  = None
        self.setFixedSize(42, 42)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("drag or wheel to change replay speed\n"
                        "double-click (or the 1x button) resets to real time")

    def _f(self, v=None):
        v = self.val if v is None else v
        return float(np.log(v / self.lo) / np.log(self.hi / self.lo))

    def set_val(self, v, emit=True):
        v = float(min(max(v, self.lo), self.hi))
        if abs(v - self.val) < 1e-9:
            return
        self.val = v
        self.update()
        if emit:
            self.changed.emit(v)

    def _set_f(self, f):
        self.set_val(self.lo * (self.hi / self.lo) ** min(max(f, 0.0), 1.0))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._y = ev.position().y()

    def mouseMoveEvent(self, ev):
        if self._y is None:
            return
        dy, self._y = self._y - ev.position().y(), ev.position().y()
        self._set_f(self._f() + dy / 120.0)

    def mouseReleaseEvent(self, ev):
        self._y = None

    def mouseDoubleClickEvent(self, ev):
        self.set_val(self.detent)

    def wheelEvent(self, ev):
        s = ev.angleDelta().y() / 120.0
        if s:
            self._set_f(self._f() + s * 0.04)

    def _spoke(self, p, r, f, r0, r1, col, w):
        a  = np.radians(225.0 - 270.0 * f)      # 8 o'clock -> 4 o'clock, cw
        c0 = r.center()
        p.setPen(QPen(QColor(col), w))
        p.drawLine(QPointF(c0.x() + r0*np.cos(a), c0.y() - r0*np.sin(a)),
                   QPointF(c0.x() + r1*np.cos(a), c0.y() - r1*np.sin(a)))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r  = QRectF(6, 6, self.width() - 12, self.height() - 12)
        rr = r.width() / 2.0
        p.setPen(QPen(QColor("#2a3540"), 3.0))
        p.drawArc(r, 225*16, -270*16)
        f = self._f()
        p.setPen(QPen(QColor("#6fa8c9"), 3.0))
        p.drawArc(r, 225*16, int(-270*16*f))
        self._spoke(p, r, self._f(self.detent), rr - 4, rr + 3, "#4c6272", 1.2)
        self._spoke(p, r, f, rr - 9, rr - 1, "#cfe6f5", 2.0)
        p.end()

class Timeline(QWidget):
    """Scrub bar over the cine buffer.  Labelled relative to the newest frame,
    so the strip reads directly as how far back in time you are."""
    scrubbed = Signal(float)            # seconds from the oldest held frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self.span = 0.0                 # seconds held
        self.pos  = 0.0                 # play head
        self.live = True                # recording: no head, whole bar filled
        self._drag = False
        self.setFixedHeight(40)
        self.setCursor(Qt.SizeHorCursor)

    def track(self):
        return QRectF(9, 7, max(1.0, self.width() - 18), 13)

    def _t_at(self, x):
        r = self.track()
        return min(max((x - r.left()) / r.width(), 0.0), 1.0) * self.span

    def _x_at(self, t):
        r = self.track()
        return r.left() + r.width() * (t / self.span if self.span > 0 else 0.0)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self.live and self.span > 0:
            self._drag = True
            self.scrubbed.emit(self._t_at(ev.position().x()))

    def mouseMoveEvent(self, ev):
        if self._drag:
            self.scrubbed.emit(self._t_at(ev.position().x()))

    def mouseReleaseEvent(self, ev):
        self._drag = False

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.track()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#161e26")))
        p.drawRoundedRect(r, 3, 3)
        p.setFont(QFont("Consolas", 7))
        fm = QFontMetrics(p.font())
        if self.span <= 0.0:
            p.setPen(QPen(QColor(DIM)))
            p.drawText(QPointF(r.left() + 6, r.center().y() + fm.ascent()/2 - 1),
                       "cine buffer empty")
            p.end(); return

        if self.live:                   # recording: the whole span is "now"
            p.setBrush(QBrush(QColor("#23404f")))
            p.drawRoundedRect(r, 3, 3)
        else:
            fr = QRectF(r.left(), r.top(), max(1.0, r.width()*self.pos/self.span),
                        r.height())
            p.setBrush(QBrush(QColor("#2d5670")))
            p.drawRoundedRect(fr, 3, 3)

        step = 1.0 if self.span <= 12 else (2.0 if self.span <= 30 else 5.0)
        p.setPen(QPen(QColor(DIM)))
        k = 0
        while k * step <= self.span + 1e-9:
            tv = self.span - k * step               # 0 s sits at the right edge
            x  = self._x_at(tv)
            p.drawLine(QPointF(x, r.bottom() + 1), QPointF(x, r.bottom() + 4))
            t = f"{-k*step:g}"
            tx = min(max(x - fm.horizontalAdvance(t)/2, 0.0),
                     self.width() - fm.horizontalAdvance(t))
            p.drawText(QPointF(tx, r.bottom() + 5 + fm.ascent()), t)
            k += 1

        if not self.live:
            x = self._x_at(self.pos)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#cfe6f5")))
            p.drawRoundedRect(QRectF(x - 2.5, r.top() - 3, 5, r.height() + 6), 2, 2)
        p.end()

#===============================================================================
# M-mode strip + motion audio
#===============================================================================
# QtMultimedia ships with the full PySide6 wheel but not with PySide6-Essentials,
# so it is optional: no audio device, no sound, everything else still works.
try:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
    HAVE_AUDIO = True
except Exception as _e:
    HAVE_AUDIO = False
    print(f"[no audio: {_e}]")

AUDIO_SR    = 22050
AUDIO_F_LO  = 180.0         # pitch at the FAR end of the line
AUDIO_F_HI  = 1200.0        # pitch at the NEAR end
AUDIO_GATE  = 0.04          # motion below this fraction of peak is silence
AUDIO_SENS  = 6.0           # motion -> loudness

class MotionAudio:
    """Sonifies the M-line's frame-to-frame change.

    THIS IS NOT DOPPLER, and the difference matters if you are tempted to read
    velocity into it.  A given point is re-sampled once per sweep - 48 elements
    x 177.5 us = 8.5 ms, so a 117 Hz PRF - which puts the unaliased Doppler
    limit at about 1.3 cm/s.  Blood flow is one to two orders of magnitude
    faster than that, so the phase shift between sweeps is aliased beyond
    recovery and no amount of processing gets it back.  What you hear here is
    motion ENERGY (how much the line changed) and motion POSITION (where along
    it), which is honest and useful for finding a pulsating vessel, but says
    nothing about how fast anything is moving.
    (Real PW Doppler is available on this hardware - single-element mode fires
    one element every 177.5 us for a 5.6 kHz PRF, good for 61 cm/s - but it
    costs the B-mode sweep, so it is a separate mode rather than this one.)

    Push mode rather than a QIODevice subclass: we top the sink up from a timer,
    which keeps all the synthesis on the UI thread and degrades to a dropout
    rather than a deadlock if a block is ever late."""

    def __init__(self, parent):
        self.sink = self.dev = None
        self.phase, self.amp, self.freq = 0.0, 0.0, AUDIO_F_LO
        self.gain = 0.5
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self._fill)

    def start(self):
        if not HAVE_AUDIO or self.sink is not None:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(AUDIO_SR)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        out = QMediaDevices.defaultAudioOutput()
        if out is None or not out.isFormatSupported(fmt):
            print("[no audio: default output will not take 22050 Hz mono int16]")
            return
        self.sink = QAudioSink(out, fmt)
        self.sink.setBufferSize(AUDIO_SR // 4 * 2)      # ~250 ms
        self.dev  = self.sink.start()
        self.phase, self.amp = 0.0, 0.0
        self.timer.start(15)

    def stop(self):
        self.timer.stop()
        if self.sink is not None:
            self.sink.stop()
        self.sink = self.dev = None

    def _fill(self):
        if self.dev is None:
            return
        n = min(self.sink.bytesFree() // 2, AUDIO_SR // 4)
        if n <= 0:
            return

        peak = max(mm["peak"], 1e-9)
        a = min(1.0, audio_fb["amp"] / peak * AUDIO_SENS)
        a = 0.0 if a < AUDIO_GATE else (a - AUDIO_GATE) / (1.0 - AUDIO_GATE)
        # pos 0 is end A of the line, which is drawn at the top of the strip
        f = AUDIO_F_HI * (AUDIO_F_LO / AUDIO_F_HI) ** float(audio_fb["pos"])

        # Ramp amplitude and frequency ACROSS the block instead of stepping them
        # at the block boundary - a step is a click, and at 15 ms intervals a
        # train of them is worse than the tone.  Phase comes from the cumulative
        # sum of the swept frequency so it stays continuous across blocks too.
        a1 = self.amp  + (a - self.amp)  * 0.35
        f1 = self.freq + (f - self.freq) * 0.25
        av = np.linspace(self.amp,  a1, n)
        fv = np.linspace(self.freq, f1, n)
        ph = self.phase + 2.0 * np.pi * np.cumsum(fv) / AUDIO_SR
        self.phase = float(np.mod(ph[-1], 2.0 * np.pi))
        self.amp, self.freq = float(a1), float(f1)

        w = np.sin(ph) * av * self.gain * 32000.0
        self.dev.write(np.clip(w, -32767, 32767).astype(np.int16).tobytes())

class MModeStrip(QWidget):
    """Position-along-the-line (vertical) vs time (horizontal), newest at the
    right.  Shares the B-mode's dyn/gain so the two read consistently; the
    brightness reference is the strip's own decaying peak under auto-gain, and
    full_scale() when auto is off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.setMaximumHeight(240)
        self._keep = None               # QImage does not copy - hold the buffer

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(self.rect(), QColor(PLOT_BG))

        with mm_lk:
            n, w, peak = mm["n"], mm["w"], mm["peak"]
            if n:
                # roll so the oldest surviving column is first, newest last
                data = np.roll(mm["buf"], -w, axis=1)[:, MM_COLS - n:].copy()
                span = float(mm["t"][(w - 1) % MM_COLS] -
                             mm["t"][(w - n) % MM_COLS])
            else:
                data, span = None, 0.0

        if data is None:
            p.setPen(QPen(QColor(DIM)))
            p.drawText(r, Qt.AlignCenter,
                       "M-mode: drag a line on the image")
            p.setPen(QPen(QColor(FRAME_C))); p.drawRect(r)
            p.end(); return

        ref = peak if state["auto"] else full_scale(state["apod"])
        dyn = max(float(state["dyn"]), 1e-6)
        db  = 20.0 * np.log10(data / max(ref, 1e-9) + 1e-9)
        v   = np.clip((db + float(state["gain"]) + dyn) / dyn, 0.0, 1.0)
        img = np.ascontiguousarray((v * 255.0).astype(np.uint8))

        self._keep = img
        h, wd = img.shape
        p.drawImage(r, QImage(img.data, wd, h, wd, QImage.Format_Grayscale8))

        p.setPen(QPen(QColor(DIM)))
        p.setFont(QFont("Consolas", 8))
        p.drawText(QPointF(r.left() + 4, r.top() + 12), "A")
        p.drawText(QPointF(r.left() + 4, r.bottom() - 4), "B")
        if span > 0.05:
            t = f"{span:.1f} s  ({n} sweeps, {n/span:.0f}/s)"
            p.drawText(QPointF(r.right() - 4 - QFontMetrics(p.font())
                               .horizontalAdvance(t), r.top() + 12), t)
        p.setPen(QPen(QColor(FRAME_C)))
        p.drawRect(r)
        p.end()

#===============================================================================
# main window
#===============================================================================
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TFM B-mode - {N_ELEM} element convex, monostatic "
                            f"(SAFT), GPU beamformer"
                            + ("" if HW else "  [SIMULATION]"))
        self.captures = []
        self.dialogs = []
        self.last = None
        self.tgc_lo, self.tgc_hi = TGC_MIN_DEF, TGC_MAX_DEF
        self.gap = GAP_US_DEF

        # cine review state (only meaningful while frozen)
        self.review  = []               # [(t_abs, (N, samps) int16)], oldest first
        self.rev_t   = np.zeros(0)      # their timestamps, seconds from the oldest
        self.cur_idx = -1
        self.play_t  = 0.0              # play head, seconds into the buffer
        self.playing = False
        self.speed   = SPEED_DEF
        self._play_wall = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 5); root.setSpacing(4)

        # -- control rows -----------------------------------------------------
        r1 = QHBoxLayout(); r1.setSpacing(2); root.addLayout(r1)
        r2 = QHBoxLayout(); r2.setSpacing(2); root.addLayout(r2)
        # Claimed here so it sits under r2 on screen; filled in below, next to
        # the other receive-conditioning controls it belongs with.
        rrx = QHBoxLayout(); rrx.setSpacing(2); root.addLayout(rrx)

        self.cb_signed = QCheckBox("signed"); self.cb_signed.setChecked(mode["signed"])
        self.cb_signed.toggled.connect(lambda v: mode.__setitem__("signed", v))
        r1.addWidget(self.cb_signed)

        self.cb_flip = QCheckBox("flip L/R"); self.cb_flip.setChecked(flip["on"])
        self.cb_flip.setToolTip(
            "mirror the array: tick if element 0 is the RIGHT-hand end of the "
            "probe.\nThe FPGA's element order comes from a connector drawing "
            "whose direction\nis unverified - if it was read from the far side "
            "the image is mirrored and\nnothing else looks wrong. Sweep a "
            "finger across the face and check the\nbright spot tracks the same "
            "way.\nRe-renders the geometry only; the RF is untouched, so this "
            "works while frozen.")
        self.cb_flip.toggled.connect(self.set_flip)
        r1.addWidget(self.cb_flip)

        r1.addWidget(QLabel("dead"))
        self.ed_dead = QLineEdit(",".join(str(i) for i in sorted(dead["set"])))
        self.ed_dead.setFixedWidth(112)
        self.ed_dead.setToolTip(
            "aperture positions to leave OUT of the beamformer, comma "
            "separated.\nUse for elements that receive nothing - they add only "
            "noise to the\ncoherent sum and drag the level meters. Press Enter "
            "to apply.\n\nThese are physical elements, so the list does NOT "
            "move with 'flip L/R'.\nThe FPGA still fires them and the cine "
            "recording still stores them:\nthis is a render-time mask, so "
            "clearing the box brings them straight back.")
        self.ed_dead.editingFinished.connect(self.apply_dead)
        r1.addWidget(self.ed_dead)

        self.depth_s = mkslider(r1, "depth", 2, 40, DEPTH_CM_DEF,
                                on_release=self.apply_depth, unit="cm")
        self.dly_s = mkslider(r1, "pulse→rx", 0, 500, DLY_US_DEF,
                              on_change=self.set_dly, unit="us")
        mkslider(r1, "damp", 0, 5000, GAP_US_DEF, on_release=self.set_gap,
                 width=90, unit="us")
        mkslider(r1, "c", 1400, 1650, int(C_DEF), on_change=self.set_c,
                 width=96, unit="")
        # QSlider is integer-only, so apodization rides as a percentage.
        mkslider(r1, "apod", 0, 100, int(round(APOD_DEF * 100)),
                 on_change=self.set_apod, unit="%")
        # Coherence-factor exponent, also as a percentage: 100% = the standard
        # CF, 0% = off.  See CF_DEF - this one changes what brightness means.
        mkslider(r1, "coh", 0, 300, int(round(CF_DEF * 100)),
                 on_change=self.set_cf, width=84, unit="%")
        mkslider(r1, "aperture", 5, 90, ACCEPT_DEF, on_change=self.set_accept,
                 width=84, unit="°")
        r1.addStretch(1)

        mkslider(r2, "TGC min", 0, 4095, TGC_MIN_DEF, on_change=self.set_tgc_lo,
                 width=118)
        mkslider(r2, "TGC max", 0, 4095, TGC_MAX_DEF, on_change=self.set_tgc_hi,
                 width=118)
        mkslider(r2, "dyn range", 20, 80, DYN_DEF, on_change=self.set_dyn,
                 width=96, unit="dB")
        mkslider(r2, "gain", -40, 40, GAIN_DEF, on_change=self.set_gain,
                 width=96, unit="dB")
        self.cb_auto = QCheckBox("auto gain"); self.cb_auto.setChecked(True)
        self.cb_auto.setToolTip("normalise to the per-frame peak; off = absolute "
                                "scale, use the gain slider.\nNOTE: auto gain "
                                "cancels every global gain change - use the "
                                "near/far dBFS readouts to see real level shifts")
        self.cb_auto.toggled.connect(self.set_auto)
        r2.addWidget(self.cb_auto)

        self.b_bg = QPushButton("capture bg")
        self.b_bg.setToolTip("average %d sweeps into a transmit-artifact "
                             "reference.\nPoint the probe at nothing (gel on "
                             "the face, aimed into air) first.\nRecapture "
                             "after changing TGC, pulses, or pulse→rx." % BG_AVG)
        self.b_bg.clicked.connect(self.start_bg)
        r2.addWidget(self.b_bg)

        self.cb_bg = QCheckBox("bg subtract")
        self.cb_bg.setToolTip("subtract the phase-aligned reference from every "
                              "sweep (live and replay).\nRemoves ~16 dB of the "
                              "repeatable ringdown/feedthrough artifact.\n"
                              "Cannot remove a CLIPPED artifact - keep the "
                              "near meter below 0 dBFS.")
        self.cb_bg.toggled.connect(lambda v: bg.__setitem__("on", bool(v)))
        r2.addWidget(self.cb_bg)

        self._receive_row(rrx)

        # -- M-mode -----------------------------------------------------------
        # Built here, before the checkbox that shows them, so the toggle handler
        # can never run against a half-constructed strip.
        self.mstrip = MModeStrip()
        self.mstrip.setVisible(False)
        self.audio  = MotionAudio(self)

        self.cb_mm = QCheckBox("M-mode")
        self.cb_mm.setToolTip(
            "scroll a line through time under the image.\n\nDrag on empty image "
            "space to place the line, drag either end (or the middle)\nto move "
            "it - endpoints are in metres, so it stays on the tissue through\n"
            "zoom, pan and depth changes. Drawn radially it is classic M-mode.\n"
            "Existing calipers stay draggable; new ones are suspended while "
            "this is on.\n\nOne column per SWEEP, not per rendered frame, so "
            "the time axis is even.")
        self.cb_mm.toggled.connect(self.set_mmode)
        r2.addWidget(self.cb_mm)

        self.cb_snd = QCheckBox("sound")
        self.cb_snd.setEnabled(HAVE_AUDIO)
        self.cb_snd.setToolTip(
            "sonify motion along the M-line: loudness = how much the line "
            "changed\nsweep to sweep, pitch = where along it (A high, B low).\n\n"
            "NOT Doppler. At 117 Hz sweep rate the unaliased velocity limit is "
            "~1.3 cm/s,\nso blood flow is aliased beyond recovery - this hears "
            "THAT something moved,\nnot how fast."
            + ("" if HAVE_AUDIO else "\n\nQtMultimedia not installed."))
        self.cb_snd.toggled.connect(self.set_sound)
        r2.addWidget(self.cb_snd)

        mkslider(r2, "vol", 0, 100, 50, on_change=self.set_vol,
                 width=70, unit="%")
        r2.addStretch(1)
        r2.addSpacing(14)
        self.wininfo = QLabel(""); self.wininfo.setStyleSheet(f"color:{DIM};")
        r2.addWidget(self.wininfo)

        # -- probe calibration + transmit ---------------------------------------
        r3 = QHBoxLayout(); r3.setSpacing(2); root.addLayout(r3)
        r4 = QHBoxLayout(); r4.setSpacing(2); root.addLayout(r4)
        self._calib_row(r3)
        self._pulser_rows(r3, r4)

        # -- scene + cine transport + side panel ------------------------------
        mid = QHBoxLayout(); mid.setSpacing(6); root.addLayout(mid, 1)
        self.scene = Scene(self)
        col = QVBoxLayout(); col.setSpacing(4)
        col.addWidget(self.scene, 1)
        col.addWidget(self.mstrip)          # hidden until M-mode is ticked
        col.addWidget(self._cine_bar())     # built before the panel: FREEZE's
        mid.addLayout(col, 1)               # handler touches it
        mid.addWidget(self._side_panel())
        self.scene.ov.zoomed.connect(self._zoom_text)

        # -- capture drawer ---------------------------------------------------
        self.drawer_box = QWidget()
        dl = QHBoxLayout(self.drawer_box)
        dl.setContentsMargins(4, 4, 4, 4); dl.setSpacing(5)
        dl.addStretch(1)
        self.drawer_layout = dl
        self.drawer = QScrollArea()
        self.drawer.setWidgetResizable(True)
        self.drawer.setFixedHeight(THUMB_H + 26)
        self.drawer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.drawer.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.drawer.setWidget(self.drawer_box)
        root.addWidget(self.drawer)

        self.status = QLabel("starting…")
        self.status.setStyleSheet(f"color:{OK_C};")
        root.addWidget(self.status)

        # -- timers -----------------------------------------------------------
        self.t_draw = QTimer(self); self.t_draw.timeout.connect(self._tick)
        self.t_draw.start(16)
        self.t_stat = QTimer(self); self.t_stat.timeout.connect(self._status)
        self.t_stat.start(250)
        # replay clock: 10 ms is finer than any frame interval we can record,
        # so the play head lands on the right frame even at 4x
        self.t_play = QTimer(self); self.t_play.timeout.connect(self._play_tick)

        for key, fn in ((Qt.Key_Space,  self._space),
                        (Qt.Key_Escape, lambda: self.b_freeze.setChecked(False)),
                        (Qt.Key_Comma,  lambda: self.step(-1)),
                        (Qt.Key_Period, lambda: self.step(+1))):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

        self._cine_enable(False)
        self.pls_refresh()          # fills the f0/frame-rate readout at startup
        self.resize(1320, 900)

    # -- receive conditioning -------------------------------------------------
    # Everything here is CPU-side, between the ADC words and the beamformer:
    # no FPGA traffic, so it works on replayed cine exactly as it does live.
    # Both controls attack the DEEP noise floor and neither touches the near
    # field, which is clutter-limited rather than noise-limited - if the far
    # field cleans up and the near field does not, that is the tell that the
    # deep haze was electronic and not tissue.
    def _receive_row(self, row):
        lab = QLabel("receive:"); lab.setStyleSheet(f"color:{DIM};")
        row.addWidget(lab)

        self.cb_band = QCheckBox("bandpass")
        self.cb_band.setChecked(BAND_ON_DEF)
        self.cb_band.setToolTip(
            "band-limit the RF before the envelope, inside the Hilbert FFT that "
            "already runs.\n\nOff, the envelope carries AFE noise over the whole "
            "0-20 MHz Nyquist span\nwhile the echo only occupies the probe's "
            "band. Keeping B MHz of it drops\n10*log10(20/B) dB of noise: the "
            "5 MHz default is about 6 dB, free.\n\nCosts nothing where the image "
            "is clutter-limited, which is most of the near field.")
        self.cb_band.toggled.connect(self.set_band_on)
        row.addWidget(self.cb_band)

        band_tip = ("passband centre and full width, in MHz.\n\nCentre it on the "
                    "pulser's f0 (the transmit row's readout) - the two-way\n"
                    "response of a CH6-2 sits inside 2-6 MHz, so 4.0 +/- 2.5 "
                    "keeps all of it.\n\nWidth is also a range-resolution floor "
                    "(c/2B): 5 MHz is 0.15 mm, well\ninside the ~0.4 mm the "
                    "two-cycle pulse gives, but below ~2 MHz you start\npaying "
                    "in axial detail. The skirts are raised cosines, so "
                    "narrowing does\nnot ring - a brick wall would, and time "
                    "ringing back-projects as arcs.")
        self.s_bf0 = mkfslider(row, "band f0", 1.0, 9.0, 0.1, BAND_F0_DEF,
                               self.set_band_f0, width=96, unit="M",
                               fmt="%.1f", tip=band_tip)
        self.s_bbw = mkfslider(row, "width", 1.0, 12.0, 0.1, BAND_BW_DEF,
                               self.set_band_bw, width=96, unit="M",
                               fmt="%.1f", tip=band_tip)

        self.cb_mf = QCheckBox("pulse comp")
        self.cb_mf.setChecked(MF_ON_DEF)
        self.cb_mf.setToolTip(
            "matched filter: cross-correlate the RF with the transmit "
            "waveform, inside the\nHilbert FFT that already runs.\n\nThis is "
            "the receive half of coded excitation. With the chirp on, every "
            "echo is\nthe whole sweep long and the raw envelope smears it "
            "over that length;\ncompression collapses each echo to ~1/"
            "bandwidth wide while summing the\nenergy of the full sweep "
            "(~15 dB over a 2-cycle burst at the same voltage).\n\nThe "
            "reference is rebuilt from the pulser's own quantised edge times "
            "whenever\na transmit setting changes, so it always matches what "
            "is firing NOW - on a\nfrozen or replayed loop recorded with "
            "different transmit settings it will\nmis-match; re-record after "
            "changing the chirp.\n\nWorks on the plain burst too (short "
            "matched filter), where it mostly re-shades\nrather than "
            "sharpens.  Compressed-pulse range sidelobes ring axially at\n"
            "about -13 dB for an unweighted chirp; the bandpass skirts "
            "double as the\ntaper that pushes them down, so leave bandpass "
            "on and centred on the sweep.")
        self.cb_mf.toggled.connect(self.set_mf)
        row.addWidget(self.cb_mf)

        # The tooltip has to carry the coherent/incoherent distinction: it is
        # the reason this is worth more than the persistence control it looks
        # like, and the reason it lives before the Hilbert rather than after.
        self.s_avg = mkslider(row, "avg", 1, AVG_MAX, AVG_DEF,
                              on_change=self.set_avg, width=96, unit=" sw")
        self.s_avg.setToolTip(
            "average the last N sweeps of RF before the envelope.\n\nThe echo "
            "repeats sweep to sweep and the noise does not, so the mean gains\n"
            "sqrt(N) on anything uncorrelated - 8 sweeps is 9 dB. This is "
            "COHERENT\naveraging: done here the noise cancels against its own "
            "sign, whereas\naveraging magnitudes after the beamformer only "
            "smooths speckle (by then\nthe noise is a rectified positive bias, "
            "and averaging cannot remove a bias).\n\nCost is motion: N sweeps at "
            "~130/s is N*7.7 ms of integration, so 8 is ~60 ms.\nPhantoms take "
            "the maximum; anything pulsatile wants 1-4.\n\nThe far dBFS meter "
            "reads the averaged data, so stepping 1 -> 8 measures how\nmuch of "
            "your deep signal was noise: ~9 dB drop means it was all noise.")

        self.cb_jit = QCheckBox("de-jitter")
        self.cb_jit.setChecked(JIT_ON_DEF)
        self.cb_jit.setToolTip(
            "put all 48 elements on one timebase using the transmit artifact as "
            "a fiducial.\n\nThe artifact is made by the same HV edge that fires "
            "tx_sync, at a fixed delay,\nso where it sits in the window IS the "
            "capture-start error - and every echo\nbehind it is displaced by the "
            "same amount. Shifting each row back by that\namount removes the "
            "error from the coherent sum.\n\nCatches both sources: the ADC "
            "free-runs against clk_in and the sample FIFO is\ntwo samples wide, "
            "so the window can only open on a 50 ns boundary (~18 deg\nRMS at "
            "3.57 MHz, which puts the clutter floor at -27 dB - ABOVE what 70%\n"
            "apod buys); and S_HDR slides the range gate under bus backpressure, "
            "which\nthe holes counter cannot see at all.\n\nNEEDS A BACKGROUND "
            "REFERENCE - press 'capture bg' first. Independent of\n'bg subtract'; "
            "either can be on without the other.\n\nWorks best at avg 1: the "
            "averager blends sweeps that were each displaced\ndifferently, so a "
            "shift measured after it is already a compromise.")
        self.cb_jit.toggled.connect(self.set_jit)
        row.addWidget(self.cb_jit)

        b_rvb = QPushButton("reverb scan")
        b_rvb.setToolTip(
            "hunt for MULTIPLE REFLECTIONS by looking for periodicity in "
            "range.\n\nA layer that bounces off the probe face repeats at 2x, "
            "3x, 4x its depth;\ntwo layers ring at their spacing. Tissue has no "
            "such period, so a peak in\nthe autocorrelation of the range "
            "profile is the signature - nothing else in\nthe image is "
            "periodic.\n\nWorks on the dB profile (multiples decay "
            "geometrically, so in dB they all\ncount equally), detrended to "
            "remove attenuation and TGC, averaged over 12\nradial lines to push "
            "speckle down.\n\nOpens live - leave it up while you press, and "
            "confirm any peak with a 2-3 cm\nwater or gel standoff: a "
            "probe-face multiple moves, tissue does not.")
        b_rvb.clicked.connect(self.open_reverb)
        row.addWidget(b_rvb)

        self.rx_lbl = QLabel(""); self.rx_lbl.setStyleSheet(f"color:{DIM};")
        row.addWidget(self.rx_lbl)
        self.jit_lbl = QLabel(""); self.jit_lbl.setStyleSheet(f"color:{DIM};")
        row.addWidget(self.jit_lbl)
        row.addStretch(1)

    def set_jit(self, v):
        state["jit"] = bool(v)
        self._refresh_rx()

    def set_mf(self, v):
        state["mf"] = bool(v)
        self._refresh_rx()

    def open_reverb(self):
        dlg = ReverbDialog(self)
        self.dialogs.append(dlg)
        dlg.show()

    def set_band_on(self, v):
        state["band_on"] = bool(v)
        self._refresh_rx()

    def set_band_f0(self, v):
        state["band_f0"] = float(v)
        self._refresh_rx()

    def set_band_bw(self, v):
        state["band_bw"] = float(v)
        self._refresh_rx()

    def set_avg(self, v):
        rf_avg.set_n(v)
        self._refresh_rx()

    def _refresh_rx(self):
        """A CPU-side receive setting moved.  Live sweeps pick it up on the next
        frame by themselves; a frozen one has to be pushed back through the
        worker or the image would keep showing the old filter."""
        if state["frozen"] and self.review:
            self._seek(self.play_t, force=True)

    # -- probe calibration ----------------------------------------------------
    # R, pitch and t0 all move the DELAY MODEL only - no FPGA traffic - so they
    # stay live while frozen and while replaying cine.  That is the whole point:
    # freeze on a wire target, then drag until it is a point.  Suggested order,
    # because they trade off against each other in a fixed way:
    #
    #   1. c   - water is 1480, tissue ~1540.  Sets the depth scale.
    #   2. t0  - a pure depth shift; put the wire at its measured depth.
    #   3. R   - asymmetric smear.  Wrong R bends the array off the true arc,
    #            so the two halves focus at different depths.
    #   4. pitch - lateral smear that grows toward the aperture edges.
    #
    # Do it on an OFF-AXIS wire: on-axis, a pitch error is nearly invisible
    # because every element is roughly equidistant.
    def _calib_row(self, row):
        lab = QLabel("probe:"); lab.setStyleSheet(f"color:{DIM};")
        row.addWidget(lab)
        mkfslider(row, "R", 40.0, 120.0, 0.1, geom["R_mm"], self.set_R,
                  width=96, unit="mm", fmt="%.1f",
                  tip="convex radius of curvature.\nMeasured: R = (chord^2/4 + "
                      "sag^2) / 2*sag.  CH6-2 face is 62.32 mm across with a "
                      "7.62 mm\nsagitta -> 67.5 mm.  Wrong R focuses the two "
                      "halves of the array at different depths.")
        mkfslider(row, "pitch", 0.200, 0.600, 0.001, geom["pitch_mm"],
                  self.set_pitch, width=96, unit="mm", fmt="%.3f",
                  tip="element pitch along the arc = arc length / element count."
                      "\nCH6-2: 64.79 mm of arc over 192 elements -> 0.3375 mm."
                      "\nA 1% error is ~half a wavelength of round-trip error at "
                      "the aperture edge.")
        mkfslider(row, "t0", T0_NS_MIN, T0_NS_MAX, T0_NS_STEP, state["t0_ns"],
                  self.set_t0, width=96, unit="ns", fmt="%.0f",
                  tip="fixed round-trip offset the geometry cannot see: lens + "
                      "matching layer\n(~2 us round trip) plus tx-to-capture "
                      "skew.  Positive = echoes arrive later.\nRECONSTRUCTION "
                      "ONLY - sends nothing to the FPGA, unlike pulse->rx.")
        row.addSpacing(10)

    # -- transmit sequencer ---------------------------------------------------
    # Same PulserCtl the Tk hosts drive, so the settings and their meanings are
    # identical; only the widgets are Qt.  One field is deliberately missing:
    # "rx us".  send_pls_rx owns the pulser's receive window because it has to
    # cover the capture window, and a manual slider would only fight the depth
    # control.  Everything else is a straight port.
    def _pulser_rows(self, r3, r4):
        self.cb_arm = QCheckBox("PULSER RUN")
        self.cb_arm.setChecked(pulser.arm)
        self.cb_arm.setToolTip(PLS_HELP.get("PULSER RUN", ""))
        self.cb_arm.toggled.connect(self.set_arm)
        r3.addWidget(self.cb_arm)

        b_fclr = QPushButton("clr fault")
        b_fclr.setToolTip(PLS_HELP.get("clr fault", ""))
        b_fclr.clicked.connect(lambda: (pulser.clear_fault(), self.pls_refresh()))
        r3.addWidget(b_fclr)

        self.cb_single = QCheckBox("single element")
        self.cb_single.setToolTip(PLS_HELP.get("single element", ""))
        self.cb_single.toggled.connect(self.set_single)
        r3.addWidget(self.cb_single)

        self.cb_chirp = QCheckBox("chirp")
        self.cb_chirp.setChecked(pulser.chirp_on)
        self.cb_chirp.setToolTip(PLS_HELP.get("chirp", ""))
        self.cb_chirp.toggled.connect(self.set_chirp)
        r3.addWidget(self.cb_chirp)

        # Coded excitation.  The setters only transmit while the chirp box is
        # ticked (each change re-uploads the whole table); unticked they just
        # park values, exactly like the element slider below.  They live on r3
        # beside their checkbox - r4 is already full of burst sliders.
        def chirp_slider(label, lo, hi, step, val, setter):
            def on(v):
                setter(v)
                self.pls_refresh()
            return mkfslider(r3, label, lo, hi, step, val, on, width=80,
                             unit="", fmt="%.1f", tip=PLS_HELP.get(label),
                             quant=lambda v: round(float(v), 1))
        chirp_slider("chirp f0 M", 0.5, 8.0, 0.1, pulser.chirp_f0_mhz,
                     pulser.set_chirp_f0_mhz)
        chirp_slider("chirp f1 M", 0.5, 8.0, 0.1, pulser.chirp_f1_mhz,
                     pulser.set_chirp_f1_mhz)
        chirp_slider("chirp us", 1.0, 40.0, 0.5, pulser.chirp_us,
                     pulser.set_chirp_us)
        r3.addStretch(1)

        # Row 4: burst shape, then the inter-stage waits and element selection.
        # settle/inhibit start at their datasheet floors - the FPGA clamps
        # anything lower regardless, so the slider cannot ask for an unsafe one.
        def pls(label, lo, hi, step, val, setter, quant, unit, fmt="%g", width=88):
            def on(v):
                setter(v)
                self.pls_refresh()
            return mkfslider(r4, label, lo, hi, step, val, on, width=width,
                             unit=unit, fmt=fmt, tip=PLS_HELP.get(label),
                             quant=quant)

        pls("pulses", 1, 16, 1, pulser.n_cycles, pulser.set_n_cycles,
            int, "", "%.0f", width=64)
        pls("width ns", 10, 500, 10, pulser.t_drive_ns, pulser.set_t_drive_ns,
            pls_ns_to_cyc, "ns", "%.0f")
        pls("dead ns", 10, 200, 10, pulser.t_dead_ns, pulser.set_t_dead_ns,
            pls_ns_to_cyc, "ns", "%.0f")
        pls("settle us", T_SETTLE_MIN_US, 40, 0.5, pulser.t_settle_us,
            pulser.set_t_settle_us, pls_us_to_cyc, "us", "%.1f")
        pls("inhibit us", T_INHIBIT_MIN_US, 40, 0.5, pulser.t_inhib_us,
            pulser.set_t_inhib_us, pls_us_to_cyc, "us", "%.1f")
        pls("ring us", 0, 50, 0.5, pulser.t_ring_us, pulser.set_t_ring_us,
            pls_us_to_cyc, "us", "%.1f")
        pls("elements", 1, N_ELEM_MAX, 1, pulser.n_elem, pulser.set_n_elem,
            int, "", "%.0f", width=76)

        # The element slider only transmits while "single element" is ticked;
        # otherwise it just parks a value for when you tick it.
        self.elem_v = 0
        def elem_moved(v):
            self.elem_v = int(v)
            if self.cb_single.isChecked():
                pulser.set_single_elem(self.elem_v)
                self.pls_refresh()
        mkfslider(r4, "element", 0, N_ELEM_MAX - 1, 1, 0, elem_moved,
                  width=76, unit="", fmt="%.0f", tip=PLS_HELP.get("element"))

        r4.addStretch(1)
        self.pls_lbl = QLabel(""); self.pls_lbl.setStyleSheet(f"color:{DIM};")
        r4.addWidget(self.pls_lbl)
        self.pace_lbl = QLabel(""); self.pace_lbl.setStyleSheet("color:#fa5;")
        r3.addWidget(self.pace_lbl)

    def pls_refresh(self):
        """Derived transmit readout, plus the pacing guard.

        SRC_SEQ arms, waits for tx_sync, captures, then holds off seq_gap before
        re-arming; a burst arriving inside that cycle is ignored.  If the pulser
        were faster than the capture we would silently keep only every Nth
        element - and with an even N over an even aperture that means seeing
        only the even ones, which looks exactly like half a dead array.
        send_pls_rx sizes t_rx to make this impossible, so the warning should
        never appear; it is here to catch that rule being wrong, not the user.
        """
        if pulser.chirp_on:
            tx = ("chirp %.1f-%.1f MHz  burst %.1f us"
                  % (pulser.chirp_f0_mhz, pulser.chirp_f1_mhz,
                     pulser.burst_ns() / 1e3))
        else:
            tx = ("f0 %.2f MHz  burst %.0f ns"
                  % (pulser.f0_hz() / 1e6, pulser.burst_ns()))
        self.pls_lbl.setText(
            "%s  elem %.0f us  frame %.1f ms (%.1f fps)%s"
            % (tx, pulser.element_period_us(), pulser.frame_ms(),
               1e3 / max(pulser.frame_ms(), 1e-6),
               "" if pulser.arm else "   [STOPPED]"))
        capture_us = state["dly_us"] + cfg["win_us"] + self.gap
        element_us = pulser.element_period_us()
        if element_us < capture_us:
            n = int(capture_us // element_us) + 1
            self.pace_lbl.setText(
                "PACING: element period %.0f us < capture %.0f us -> only every "
                "%d%s burst captured" % (element_us, capture_us, n,
                                         {1: "st", 2: "nd", 3: "rd"}.get(n, "th")))
        else:
            self.pace_lbl.setText("")

    # -- cine transport bar ---------------------------------------------------
    def _cine_bar(self):
        bar = QFrame(); bar.setObjectName("panel")
        h = QHBoxLayout(bar); h.setContentsMargins(7, 4, 7, 4); h.setSpacing(5)

        self.b_play   = GlyphButton("play",  "play the cine loop  (space)")
        self.b_stepb  = GlyphButton("step-", "previous frame  (,)")
        self.b_stepf  = GlyphButton("step+", "next frame  (.)")
        self.b_rep    = GlyphButton("repeat", "loop back to the start at the end",
                                    checkable=True)
        self.b_rep.setChecked(True)
        self.b_play.clicked.connect(self.toggle_play)
        self.b_stepb.clicked.connect(lambda: self.step(-1))
        self.b_stepf.clicked.connect(lambda: self.step(+1))
        for b in (self.b_play, self.b_stepb, self.b_stepf, self.b_rep):
            h.addWidget(b)

        self.tl = Timeline()
        self.tl.scrubbed.connect(self.scrub)
        h.addWidget(self.tl, 1)

        self.cine_lbl = QLabel("")
        self.cine_lbl.setStyleSheet(f"color:{DIM};")
        self.cine_lbl.setFixedWidth(178)
        self.cine_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.cine_lbl)

        kv = QVBoxLayout(); kv.setSpacing(0); kv.setContentsMargins(2, 0, 0, 0)
        self.knob = Knob(SPEED_MIN, SPEED_MAX, SPEED_DEF)
        self.knob.changed.connect(self.set_speed)
        kv.addWidget(self.knob, 0, Qt.AlignHCenter)
        self.spd_lbl = QLabel("1.00x")
        self.spd_lbl.setStyleSheet(f"color:{DIM};")
        self.spd_lbl.setAlignment(Qt.AlignHCenter)
        kv.addWidget(self.spd_lbl)
        h.addLayout(kv)

        b_1x = QPushButton("1x")
        b_1x.setToolTip("back to real time")
        b_1x.setFixedWidth(30)
        b_1x.clicked.connect(lambda: self.knob.set_val(SPEED_DEF))
        h.addWidget(b_1x)
        return bar

    # -- side panel -----------------------------------------------------------
    def _side_panel(self):
        panel = QFrame(); panel.setObjectName("panel"); panel.setFixedWidth(248)
        v = QVBoxLayout(panel); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        self.b_freeze = QPushButton("FREEZE")
        self.b_freeze.setCheckable(True)
        self.b_freeze.setFixedHeight(30)
        self.b_freeze.setToolTip(f"pause and review the last {CINE_SECONDS:.0f} s "
                                 f"on the timeline below the image  (space)")
        self.b_freeze.toggled.connect(self.set_frozen)
        v.addWidget(self.b_freeze)

        self.b_cap = QPushButton("CAPTURE")
        self.b_cap.setFixedHeight(30)
        self.b_cap.clicked.connect(self.do_capture)
        v.addWidget(self.b_cap)

        self.b_set = QPushButton("save settings")
        self.b_set.setToolTip(
            "write every control on this window to host/settings/ as JSON, with "
            "a PNG\nof the current image beside it - latest.json is always the "
            "newest, and a\ntimestamped copy is kept alongside it.\n\nRecords the "
            "LIVE state, not the slider positions: clamped band edges, how many\n"
            "sweeps the averager actually holds, the level meters and the jitter "
            "numbers.\n\nShift-click to attach a note (what the probe is on, what "
            "you are looking at).")
        self.b_set.clicked.connect(self.save_settings)
        v.addWidget(self.b_set)
        self.set_lbl = QLabel("")
        self.set_lbl.setStyleSheet(f"color:{DIM};")
        v.addWidget(self.set_lbl)

        row0 = QHBoxLayout(); row0.setSpacing(4)
        self.zoom_lbl = QLabel("zoom 1.0x")
        self.zoom_lbl.setStyleSheet(f"color:{DIM};")
        b_rst = QPushButton("reset view"); b_rst.clicked.connect(self.reset_view)
        row0.addWidget(self.zoom_lbl); row0.addStretch(1); row0.addWidget(b_rst)
        v.addLayout(row0)

        lb = QLabel("last capture"); lb.setStyleSheet(f"color:{DIM};")
        v.addWidget(lb)
        self.preview = QLabel()
        self.preview.setFixedHeight(186)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"border:1px solid #22303a; background:{PLOT_BG};"
                                   f"color:{DIM};")
        self.preview.setText("no captures yet")
        v.addWidget(self.preview)

        row = QHBoxLayout(); row.setSpacing(4)
        self.b_open = QPushButton("open"); self.b_open.clicked.connect(self.open_last)
        self.b_save = QPushButton("save PNG…"); self.b_save.clicked.connect(self.save_last)
        self.b_open.setEnabled(False); self.b_save.setEnabled(False)
        row.addWidget(self.b_open); row.addWidget(self.b_save)
        v.addLayout(row)

        v.addSpacing(4)
        b_clr = QPushButton("clear measurements")
        b_clr.clicked.connect(self.scene.ov.clear_measures)
        v.addWidget(b_clr)
        self.meas_lbl = QLabel("no measurements")
        self.meas_lbl.setWordWrap(True)
        self.meas_lbl.setStyleSheet(f"color:{MEAS_C};")
        v.addWidget(self.meas_lbl)
        self.scene.ov.changed.connect(self._meas_text)

        v.addStretch(1)
        tip = QLabel("wheel zooms about the cursor\n"
                     "middle- or ctrl-drag pans\n"
                     "double-click resets the view\n"
                     "drag on the image to measure\n"
                     "drag an end or the middle to adjust\n"
                     "right-click a line to delete\n"
                     "click a thumbnail to reopen it\n"
                     "\n"
                     "space freezes, then plays the loop\n"
                     "drag the timeline to go back in time\n"
                     ", and . step one frame\n"
                     "esc goes back to live")
        tip.setStyleSheet(f"color:{DIM};")
        v.addWidget(tip)
        return panel

    def _meas_text(self):
        ms = self.scene.ov.measures
        if not ms:
            self.meas_lbl.setText("no measurements")
        else:
            self.meas_lbl.setText("   ".join(f"{i+1}: {meas_mm(m):.1f} mm"
                                             for i, m in enumerate(ms)))

    def _zoom_text(self):
        self.zoom_lbl.setText(f"zoom {view['zoom']:.1f}x")

    def reset_view(self):
        reset_view()
        self._zoom_text()
        self.scene.gl.update()

    # -- control callbacks ----------------------------------------------------
    # dly and gap both move the end of the capture cycle, so both have to resize
    # the pulser's receive window with them - see send_pls_rx.
    def set_dly(self, v):
        state["dly_us"] = float(v)
        send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(v)), "seq_dly")
        send_pls_rx(v, self.gap)
        self.pls_refresh()      # t_rx moved, so element period and frame rate did

    def set_gap(self, v):
        self.gap = v
        send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(v)), "seq_gap")
        send_pls_rx(state["dly_us"], v)
        self.pls_refresh()

    # these are pure shader uniforms - repaint explicitly so they stay live
    # while frozen (only the compress pass re-runs for dyn range / gain)
    def set_flip(self, v):    flip["on"] = bool(v);       self.scene.gl.update()

    def apply_dead(self):
        """Re-parse the box, normalise what it shows, and repaint.  Render-time
        only - no FPGA traffic, and it works while frozen or scrubbing."""
        set_dead(self.ed_dead.text())
        txt = ",".join(str(i) for i in sorted(dead["set"]))
        if txt != self.ed_dead.text():
            self.ed_dead.setText(txt)       # echo back what was actually taken
        self.scene.gl.update()
    def set_c(self, v):       state["c"] = float(v);      self.scene.gl.update()
    def set_accept(self, v):  state["accept"] = float(v); self.scene.gl.update()
    def set_mmode(self, on):
        mline["on"] = bool(on)
        self.mstrip.setVisible(mline["on"])
        mm_reset()                      # stale history never survives a re-arm
        if not mline["on"] and self.cb_snd.isChecked():
            self.cb_snd.setChecked(False)   # no line, nothing to listen to
        self.scene.ov.update()

    def set_sound(self, on):
        if on and not mline["on"]:
            self.cb_mm.setChecked(True)     # sound implies the line exists
        self.audio.start() if on else self.audio.stop()

    def set_vol(self, v):     self.audio.gain = v / 100.0

    def set_apod(self, v):    state["apod"] = v / 100.0;  self.scene.gl.update()
    def set_cf(self, v):      state["cf"]   = v / 100.0;  self.scene.gl.update()
    def set_t0(self, v):      state["t0_ns"] = float(v);  self.scene.gl.update()

    # R and pitch rebuild the element table, which bumps geom["gen"] and makes
    # _beamform re-upload the 'elems' uniform on the next pass.
    def set_R(self, v):
        geom["R_mm"] = float(v); rebuild_geometry(); self.scene.gl.update()

    def set_pitch(self, v):
        geom["pitch_mm"] = float(v); rebuild_geometry(); self.scene.gl.update()

    # -- transmit callbacks ---------------------------------------------------
    def set_arm(self, on):
        pulser.set_arm(bool(on)); self.pls_refresh()

    def set_single(self, on):
        pulser.set_single_elem(self.elem_v if on else None)
        self.pls_refresh()

    def set_chirp(self, on):
        pulser.set_chirp_on(bool(on))
        self.pls_refresh()
    def set_dyn(self, v):     state["dyn"] = float(v);    self.scene.gl.update()
    def set_gain(self, v):    state["gain"] = float(v);   self.scene.gl.update()

    def _send_tgc(self):
        lo, hi = self.tgc_lo, max(self.tgc_lo, self.tgc_hi)
        inc = max(0, ((hi - lo) * 4096) // cfg["win_words"])
        send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
        send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

    def set_tgc_lo(self, v): self.tgc_lo = v; self._send_tgc()
    def set_tgc_hi(self, v): self.tgc_hi = v; self._send_tgc()

    def set_auto(self, v):
        state["auto"] = v
        self.scene.gl.update()

    def start_bg(self):
        """Arm the transmit-artifact reference capture.  The Hilbert worker
        accumulates the next BG_AVG LIVE sweeps; _tick() watches the countdown
        and restores the button text."""
        if state["frozen"]:
            return                      # nothing live to average
        bg["acc"], bg["want"] = None, BG_AVG
        self.b_bg.setText(f"capturing {BG_AVG}")

    def clear_bg(self):
        bg.update(ref=None, acc=None, n=0, want=0)
        self.cb_bg.setChecked(False)
        self.b_bg.setText("capture bg")

    def set_frozen(self, v):
        """FREEZE is also the entry point to the cine loop: it stops the
        recorder and takes a stable snapshot of everything still in it, so the
        frames cannot shift under the timeline while it is being scrubbed."""
        state["frozen"] = v
        self.b_freeze.setText("FROZEN - click to resume" if v else "FREEZE")
        if v:
            self.review, self.rev_t = cine.freeze()
            self.cur_idx = -1
            self._cine_enable(True)
            if len(self.review):
                self.play_t = float(self.rev_t[-1])     # sit on the newest frame
                self._seek(self.play_t, force=True)     # ...and show exactly it
            else:
                self._cine_text()
        else:
            # Resuming: the held sweeps predate the pause and the probe may
            # have moved, so the first live frame back must not blend the two.
            rf_avg.reset()
            self._stop_play()
            self.review, self.rev_t = [], np.zeros(0)
            self.cur_idx = -1
            with replay_lk:         # drop any in-flight request before the
                replay["rf"] = None # recorder can recycle the slot it points at
            cine.resume()
            self._cine_enable(False)
            hil_ev.set()                  # wake the worker back up

    # -- cine transport -------------------------------------------------------
    def _cine_enable(self, on):
        for w in (self.b_play, self.b_stepb, self.b_stepf, self.b_rep):
            w.setEnabled(on)
        self.tl.live = not on
        self.tl.update()

    def _span(self):
        return float(self.rev_t[-1]) if len(self.rev_t) else 0.0

    def _seek(self, t, force=False):
        """Show the frame that was live at `t` seconds into the buffer."""
        if not self.review:
            return
        t = min(max(t, 0.0), self._span())
        i = int(np.searchsorted(self.rev_t, t, side="right")) - 1
        i = min(max(i, 0), len(self.review) - 1)
        if i != self.cur_idx or force:
            self.cur_idx = i
            request_replay(self._review_rf(i))
        self.play_t = t
        self.tl.span, self.tl.pos = self._span(), t
        self.tl.update()
        self._cine_text()

    def _review_rf(self, i):
        """Recorded sweep i, averaged over the same span the live view uses.

        The cine ring stores RAW sweeps, so this has to redo the boxcar rather
        than replay one - which is the better arrangement anyway: freezing does
        not change the noise floor under the image, and a loop recorded at avg 1
        can be re-averaged after the fact by dragging the slider while frozen.

        The window is trimmed at the start of the buffer rather than padded, so
        the oldest frames average over fewer sweeps instead of reusing one."""
        n = min(rf_avg.n, i + 1)
        if n <= 1:
            return self.review[i][1]
        acc = np.zeros(self.review[i][1].shape, dtype=np.int32)
        for k in range(i - n + 1, i + 1):
            acc += self.review[k][1]
        return (acc / n).astype(np.float32)

    def _cine_text(self):
        if not self.review:
            self.cine_lbl.setText("no frames buffered")
            return
        self.cine_lbl.setText(f"{self.play_t - self._span():+6.2f} s   "
                              f"{self.cur_idx + 1}/{len(self.review)}")

    def scrub(self, t):
        self._play_wall = time.perf_counter()    # dragging must not "catch up"
        self._seek(t)

    def step(self, d):
        if not self.review or not state["frozen"]:
            return
        self._stop_play()
        i = min(max(self.cur_idx + d, 0), len(self.review) - 1)
        self._seek(float(self.rev_t[i]), force=(i == self.cur_idx))

    def toggle_play(self):
        if self.playing:
            self._stop_play()
        elif self.review:
            if self.play_t >= self._span() - 1e-6:      # parked at the end
                self._seek(0.0)
            self.playing = True
            self.b_play.set_kind("pause")
            self._play_wall = time.perf_counter()
            self.t_play.start(10)

    def _stop_play(self):
        self.playing = False
        self.t_play.stop()
        self.b_play.set_kind("play")

    def _play_tick(self):
        """Walk the play head in recorded time, so 1x replays the loop at the
        rate it was acquired at, gaps and jitter included."""
        now = time.perf_counter()
        dt, self._play_wall = now - self._play_wall, now
        t = self.play_t + dt * self.speed
        if t >= self._span():
            if self.b_rep.isChecked():
                t = 0.0 if self._span() <= 0 else t % self._span()
            else:
                self._seek(self._span())
                self._stop_play()
                return
        self._seek(t)

    def set_speed(self, v):
        self.speed = float(v)
        self.spd_lbl.setText(f"{v:.2f}x")

    def _space(self):
        if state["frozen"]:
            self.toggle_play()
        else:
            self.b_freeze.setChecked(True)

    def apply_depth(self, v):
        """Depth changes the frame size: stop, drain, swap buffers, reconfigure."""
        global raw_buf, carry, _prev_elem
        words = depth_to_words(v)
        if words == cfg["win_words"]:
            return
        mm_reset()          # a new window length: old columns are not comparable
        state["depth_cm"] = v
        # the recorded windows are the old length: nothing in them can be shown
        # against the new geometry, so the loop starts over (and cannot stay
        # frozen on frames that are about to be discarded)
        self.b_freeze.setChecked(False)
        cine.reset()
        self.clear_bg()                       # reference is the old window length
        send_cmd(cmd(OP_STOP), "stop")
        time.sleep(0.2)                       # residual old-size frames drain
        rf_avg.reset()                        # held sweeps are the old length
        with buf_lk:
            set_cfg(words)
            raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)
            carry = np.empty(0, dtype=np.uint32)
            stats["last_fcnt"] = None
            _prev_elem = -1
        send_seq_config(self.tgc_lo, max(self.tgc_lo, self.tgc_hi),
                        int(state["dly_us"]), self.gap)
        send_cmd(cmd(OP_START), "start")
        view["cz"] = None                     # depth changed: recentre vertically
        self.pls_refresh()      # send_seq_config resized t_rx with the window

    # -- capture --------------------------------------------------------------
    def info_line(self):
        return (f"{N_ELEM} el  depth {state['depth_cm']} cm  c {state['c']:.0f} m/s  "
                f"dly {state['dly_us']:.0f} us  aper {state['accept']:.0f} deg  "
                f"apod {state['apod']*100:.0f}%  "
                # Only when on: CF makes brightness non-quantitative, so a
                # capture has to carry the fact that it was applied.
                + (f"coh {state['cf']:.2f}  " if state["cf"] > 0 else "")
                # Both of these change the noise floor the image sits on, so a
                # capture is not comparable to another one without them.
                + ("band %.1f-%.1f MHz  " % tuple(f / 1e6 for f in band_edges())
                   if state["band_on"] else "")
                + (f"avg {rf_avg.n} sw  " if rf_avg.n > 1 else "")
                + (f"de-jit {jit['rms_ns']:.1f} ns rms  " if state["jit"] else "")
                + f"t0 {state['t0_ns']:+.0f} ns  "
                f"R {geom['R_mm']:.1f} mm  pitch {geom['pitch_mm']:.4f} mm  "
                f"dyn {state['dyn']:.0f} dB  gain {state['gain']:+.0f} dB  "
                f"zoom {view['zoom']:.1f}x  TGC {self.tgc_lo}-"
                f"{max(self.tgc_lo, self.tgc_hi)}"
                + (f"  cine {self.play_t - self._span():+.2f} s"
                   if state["frozen"] and self.review else "")
                + ("" if HW else "  [SIM]"))

    def do_capture(self):
        img, vb = self.scene.gl.grab_bmode()
        if img is None:
            return
        cap = Capture(img, vb, self.scene.ov.measures, self.info_line())
        self.captures.append(cap)
        self._add_thumb(cap)
        self._set_preview(cap)
        self.b_open.setEnabled(True); self.b_save.setEnabled(True)

    def _set_preview(self, cap):
        pm = QPixmap.fromImage(render_capture(cap))
        self.preview.setPixmap(pm.scaled(self.preview.width() - 4,
                                         self.preview.height() - 4,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview.setToolTip(f"#{cap.n}  {cap.stamp}")
        self.last = cap

    def _thumb_pixmap(self, cap):
        return QPixmap.fromImage(render_capture(cap)).scaledToHeight(
            THUMB_H, Qt.SmoothTransformation)

    def _add_thumb(self, cap):
        lb = ThumbLabel()
        lb.setPixmap(self._thumb_pixmap(cap))
        lb.setToolTip(f"#{cap.n}  {cap.stamp}\nclick to open · right-click to remove")
        lb.setStyleSheet("border:1px solid #2c3a45;")
        lb.setCursor(Qt.PointingHandCursor)
        lb.clicked.connect(lambda c=cap: self.open_capture(c))
        lb.removed.connect(lambda c=cap: self.remove_capture(c))
        cap.thumb_label = lb
        self.drawer_layout.insertWidget(self.drawer_layout.count() - 1, lb)
        QTimer.singleShot(0, lambda: self.drawer.horizontalScrollBar().setValue(
            self.drawer.horizontalScrollBar().maximum()))

    def capture_changed(self, cap):
        """Measurements edited in a viewer: refresh its thumbnail and preview."""
        if cap.thumb_label is not None:
            cap.thumb_label.setPixmap(self._thumb_pixmap(cap))
        if self.last is cap:
            self._set_preview(cap)

    def open_capture(self, cap):
        dlg = CaptureDialog(cap, self.capture_changed, self)
        self.dialogs.append(dlg)
        dlg.show()

    def remove_capture(self, cap):
        if cap.thumb_label is not None:
            self.drawer_layout.removeWidget(cap.thumb_label)
            cap.thumb_label.deleteLater()
            cap.thumb_label = None
        if cap in self.captures:
            self.captures.remove(cap)
        if self.last is cap:
            if self.captures:
                self._set_preview(self.captures[-1])
            else:
                self.last = None
                self.preview.setPixmap(QPixmap())
                self.preview.setText("no captures yet")
                self.b_open.setEnabled(False); self.b_save.setEnabled(False)

    def open_last(self):
        if self.last:
            self.open_capture(self.last)

    def save_last(self):
        if self.last:
            save_capture(self.last, self)

    def save_settings(self):
        """Dump the whole control state to host/settings/.  Shift attaches a
        note - the one thing the sliders cannot record is what the probe was
        pointed at, and that is usually the first question later."""
        note = ""
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            note, ok = QInputDialog.getText(self, "save settings",
                                            "note (what are we looking at?)")
            if not ok:
                return
        path = write_settings(self, note.strip())
        if path is None:
            self.set_lbl.setText("save FAILED - see console")
            self.set_lbl.setStyleSheet(f"color:{WARN_C};")
            return
        self.set_lbl.setText(f"saved settings/{os.path.basename(path)}")
        self.set_lbl.setStyleSheet(f"color:{DIM};")

    # -- frame / status -------------------------------------------------------
    def _tick(self):
        self.scene.sync_view()
        gl = self.scene.gl
        if gl.tex_gen != hil["gen"] or gl.rf_tex is None:
            gl.update()
        self.scene.ov.update()
        if mline["on"]:
            self.mstrip.update()
        # The worker disarms M-mode if mline_sample throws.  Follow it with the
        # checkbox so the UI cannot claim M-mode is on while drags are going to
        # the caliper tool, and say why.
        if self.cb_mm.isChecked() and not mline["on"]:
            self.cb_mm.setChecked(False)
            if mline["err"]:
                self.status.setText(f" M-mode disabled: {mline['err']}")
                self.status.setStyleSheet(f"color:{WARN_C};")
                mline["err"] = None
        # background capture runs on the Hilbert worker; reflect its countdown
        want = bg["want"]
        txt  = f"capturing {want}" if want else "capture bg"
        if self.b_bg.text() != txt:
            self.b_bg.setText(txt)
            if not want and bg["ref"] is not None:
                self.cb_bg.setChecked(True)     # just finished: apply it

    def _status(self):
        gl = self.scene.gl
        if not state["frozen"]:             # live: the bar shows the buffer fill
            n, secs, mb = cine.status()
            self.tl.span = secs
            self.tl.update()
            self.cine_lbl.setText(f"rec {n} f · {secs:4.1f} s · {mb:.0f} MB")
        # Both readouts are the ACTUAL state, not the slider positions: the band
        # is clamped to Nyquist and the averager fills over its first N sweeps,
        # so "8/8" is the only thing that says the full 9 dB is really there.
        lo, hi = band_edges()
        self.rx_lbl.setText(
            ("band %.1f-%.1f MHz" % (lo / 1e6, hi / 1e6)
             if state["band_on"] else "band off")
            + (f" · avg {rf_avg.depth()}/{rf_avg.n}" if rf_avg.n > 1 else ""))
        # The jitter number is a MEASUREMENT, so show it whenever it is being
        # taken - the spread is worth reading even with the correction off, and
        # railed rows are the tell that a gate slip exceeded the search window.
        if bg["ref"] is None:
            self.jit_lbl.setText("· jitter: no ref")
            self.jit_lbl.setStyleSheet(f"color:{DIM};")
        elif not jit["used"]:
            self.jit_lbl.setText("· jitter: no artifact")
            self.jit_lbl.setStyleSheet(f"color:{WARN_C};")
        else:
            # `used` matters as much as `railed`: an element that MISSED its
            # burst has no artifact where one is expected, so it fails the
            # confidence gate and drops out of `used` without ever being
            # counted as railed.  Showing only railed hides exactly that case.
            self.jit_lbl.setText(
                f"· jitter {jit['rms_ns']:.1f} ns rms, {jit['pp_ns']:.0f} ns p-p"
                f" · {jit['used']}/{N_ELEM} used"
                + (f", {jit['railed']} railed" if jit["railed"] else "")
                + ("  [corrected]" if state["jit"] else ""))
            self.jit_lbl.setStyleSheet(
                f"color:{WARN_C if jit['railed'] else DIM};")
        self.wininfo.setText(
            f"near {level['near']:+6.1f}  far {level['far']:+6.1f} dBFS"
            f"{'  [bg]' if bg['on'] and bg['ref'] is not None else ''} · "
            f"win {cfg['samps']} samp · {cfg['win_us']:.0f} us · "
            f"grid {gl.fb_w}x{gl.fb_h} · {N_ELEM} el, {APERTURE_MM:.2f} mm aperture "
            f"· R {geom['R_mm']:.1f} mm pitch {geom['pitch_mm']:.4f} mm "
            f"t0 {state['t0_ns']:+.0f} ns")
        # near is the clipping meter: colour it when the artifact is on the rail,
        # because a clipped artifact is one the subtraction cannot remove.
        self.wininfo.setStyleSheet(
            f"color:{WARN_C};" if level["near"] > -1.0 else f"color:{DIM};")
        # "holes" counts ADC samples dropped INSIDE a window (seq_check).
        # Non-zero holes with zero drops = traces are being time-corrupted
        # without any frame being lost, which is what flickering dark patches
        # deeper in the window look like.
        bad = (stats["drops"] or stats["resyncs"] or stats["seq_bad"]
               or stats["skips"])
        self.status.setText(
            f" {stats['mbps']:6.1f} MB/s   {stats['fps']/N_ELEM:6.1f} sweeps/s"
            f"   frames {stats['frames']}   drops {stats['drops']}"
            f"   resyncs {stats['resyncs']}"
            f"   holes {stats['seq_bad']}/{stats['seq_chk']}"
            f"   skips {stats['skips']}"
            f"   |  gpu {perf['gpu_ms']:.2f} ms   ui {perf['cpu_ms']:.2f} ms"
            f"   hilbert {perf['hil_ms']:.1f} ms ({FFT_LIB}, off-thread)"
            + ("" if stats["alive"] else "   *** STREAM STOPPED ***"))
        self.status.setStyleSheet(f"color:{WARN_C if bad else OK_C};")

    def closeEvent(self, ev):
        stats["alive"] = False
        self.audio.stop()                 # release the device before teardown
        hil_ev.set()                      # let the worker notice and exit
        if HW:
            try:
                send_cmd(cmd(OP_STOP), "stop")
            except SystemExit:
                pass
            time.sleep(0.1)
            for i in range(NBUF):
                d3.FT_ReleaseOverlapped(h, C.byref(ovs[i]))
            d3.FT_Close(h)
        ev.accept()

#===============================================================================
if __name__ == "__main__":
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapInterval(0)          # no vsync: lowest latency, never blocks the UI
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    win = Main()
    win.show()
    print("streaming - close the window to stop.")
    sys.exit(app.exec())
