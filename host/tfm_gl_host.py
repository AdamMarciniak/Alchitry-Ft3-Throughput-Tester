# tfm_gl_host.py
#   python tfm_gl_host.py            -> live GPU TFM B-mode with calipers
#   python tfm_gl_host.py signed     -> treat samples as 12-bit two's complement
#   python tfm_gl_host.py sim        -> no hardware; synthetic phantom (UI testing)
#   python tfm_gl_host.py flip       -> start with the array mirrored L/R
#                                       (also a checkbox; see ELEM_UNIFORM_FLIP)
#   python tfm_gl_host.py --fast17   -> apply the stable 24-shot / 17 cm profile
#   python tfm_gl_host.py --fast17 --arm -> also start transmitting after the
#                                           firmware identity check succeeds
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
# Video export: mark IN and OUT on the timeline ([ and ], keys i and o, or drag
# the flags) and "export video…" writes that range out through ffmpeg.  Every
# frame goes back through the beamformer at the export resolution, so 4K is
# reconstructed at 4K rather than upscaled from the window, with the axes,
# calipers, M-line and the settings footer painted to match.  H.264 High /
# yuv420p / bt709 at CRF, i.e. what YouTube ingests without re-wrapping.
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
import ctypes as C, sys, time, threading, os, struct, collections, json, copy
import subprocess, shutil, tempfile
import numpy as np
import moderngl
import rf_debug
from acquisition_timing import tgc_increment
from afe_settings import metadata as afe_metadata, recommended_profile, register_writes
from pulse_methods import GOLAY_CODES, RX_OFFSETS, GolayPairs, ThreeRxGroups, decode_golay, windows_per_tx, FAST17
from pulse_methods import ALTERNATING_24, BANKS, BANK_FOR_ELEMENT, SLOT_FOR_ELEMENT, BankFrame, shots_per_sweep
from rf_debug_ui import DebugMixin

pipeline_lock = threading.RLock()
debug_command_hook = None
debug_probe_consumer = None
debug_startup_commands = []
debug_discard_words = 0
debug_replay_only = False
recorded_tx_reference = None
DEBUG_SLIDERS = {}

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import (QSurfaceFormat, QImage, QPixmap, QPainter, QPen,
                           QBrush, QColor, QFont, QFontMetrics, QPolygonF,
                           QShortcut, QKeySequence)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QSlider, QPushButton,
                               QCheckBox, QHBoxLayout, QVBoxLayout, QScrollArea,
                               QFrame, QDialog, QFileDialog, QSizePolicy,
                               QLineEdit, QInputDialog, QComboBox, QDoubleSpinBox,
                               QGridLayout, QProgressDialog, QMessageBox,
                               QDialogButtonBox)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

# PulserCtl is UI-agnostic - it only wants (send_cmd, cmd) - so the transmit
# settings are shared with tfm_host.py verbatim.  build_pulser_panel is NOT:
# it is Tk, and this host is Qt, so the panel is rebuilt below in _pulser_row().
# HELP is the same tooltip text either way, which is the part worth not forking.
from pulser_ctrl import (PulserCtl, HELP as PLS_HELP, N_ELEM_MAX,
                         T_DEAD_MIN_NS, T_SETTLE_MIN_US, T_INHIBIT_MIN_US,
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
OP_AFE_REG = 0x0A
OP_SEQ_LEN, OP_SEQ_DLY, OP_SEQ_TGC = 0x0B, 0x0C, 0x0D
OP_SEQ_GAP, OP_SEQ_TGC0 = 0x0E, 0x0F
OP_SEQ_TGC1 = 0x21
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

# Startup values below marked "settings/latest.json 2026-08-15" are the working
# point that was actually on screen for the last saved image, baked in so the
# window opens where the evening left off rather than at the textbook defaults.
# Every one of them is still a live control - this only moves where they start.
C_DEF    = 1496.0           # m/s (settings/latest.json 2026-08-15; 1540 = the
                            # textbook soft-tissue figure).  Also sizes the
                            # capture window in depth_to_words(), so a lower c
                            # buys a slightly longer window for the same cm.

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
#
# Starts at 85% rather than the 70% knee (settings/latest.json 2026-08-15): with
# the capture-start jitter noted below sitting at -27 dB, the extra taper is
# still buying visible clutter reduction at a depth where the SNR can pay for it.
APOD_DEF = 0.85

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
# It changes what the image MEANS, in three ways worth knowing before turning it
# up (and worth re-reading, because the startup value below is no longer zero):
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
# 0.36 (settings/latest.json 2026-08-15): a third of the standard factor, which
# is enough to pull the haze down without flattening speckle - and, per the note
# above, gentle enough that a slightly out-of-phase aperture does not eat the
# target with it.  Set the slider to 0 for a plain delay-and-sum image.
CF_DEF = 0.36

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

# --- frequency compounding ----------------------------------------------------
# Split the selected receive passband into three power-complementary sub-bands,
# beamform each one independently, then combine their detected powers.  Anatomy
# stays registered while the wavelength-dependent speckle changes, so the power
# sum has lower speckle contrast than a single coherent full-band image.
#
# The sub-band crossovers are sin/cos pairs: q_left^2 + q_right^2 == 1.  Together
# with the outer bandpass this means the three masks preserve the full band's
# spectral power instead of making the image arbitrarily brighter or darker.
# Three bands are the useful ceiling here.  At the 5 MHz default passband each
# is about 1.7 MHz wide (c/2B ~= 0.45 mm), already near the axial resolution of
# the normal two-cycle pulse; more bands would mostly trade detail for smoothness.
FREQ_COMP_DEF   = False
FREQ_COMP_BANDS = 3
FREQ_COMP_XFADE = 0.06       # crossover width as a fraction of the full band

# --- probe passband -----------------------------------------------------------
# The CH6-2's nameplate two-way response, and the yardstick the transmit
# readout scores the drive against (tx_in_probe_band).  It is NOT measured -
# nothing in this host ever sees the transducer's response - so treat it as the
# label on the box, good to maybe half a megahertz at the skirts.  It earns its
# place anyway: drive outside it radiates nothing at all, and a chirp slider
# will happily ask for 7.3 MHz on a probe that dies at 6 without one thing on
# screen saying so.  Change these two numbers if the probe changes.
PROBE_LO_MHZ, PROBE_HI_MHZ = 2.0, 6.0

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
# The reference is built from the commanded quantised switching edges
# (pulser.tx_waveform). It does not measure the pulser, probe or two-way analog
# response. The receive bandpass limits the spectrum but cannot calibrate that
# response's phase or amplitude; real echoes can still leave range sidelobes.
# The FFT is padded by the reference length so the correlation cannot wrap the
# deep end of the window onto the shallow end.
#
# Correlation uses the reference's start as lag zero. The actual acoustic and
# analog group delay remains, so check range calibration on a known reflector
# when changing the waveform or compression reference. It
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

DEPTH_CM_DEF = 14           # ~187 us window (settings/latest.json 2026-08-15)
DLY_US_DEF   = 5            # pulse -> receive settling
GAP_US_DEF   = 50           # receive end -> next pulse (DAC ring-out)
# TGC min starts well up the range (settings/latest.json 2026-08-15): the ramp
# runs lo -> hi across the window, so lifting the FLOOR lifts the near field with
# it.  0 is the flat-out-of-the-box value; drop it back if the near meter clips.
TGC_MIN_DEF, TGC_MAX_DEF, TGC_REACH_DEF = 834, 4095, 100
# 56 dB / +36 dB with auto gain OFF (settings/latest.json 2026-08-15).  The gain
# figure only means anything against the absolute full_scale() reference, which
# is why AUTO_DEF goes with it - turning auto back on cancels it outright.
DYN_DEF, GAIN_DEF = 56, 36
AUTO_DEF = False

# Greyscale transfer curve applied AFTER the log window, as a symmetric S about
# mid-grey.  1.00 is the identity, i.e. the plain linear-in-dB ramp this host
# has always drawn; below 1.00 steepens the middle of the ramp and rolls off
# both ends.
#
# Why a scanner wants this: log compression maps a dB window onto 0..1 with a
# constant dB-per-grey-level, which spends just as much of the ramp on the
# noise floor and on the specular highlights as it does on tissue - and tissue
# is the only part anyone reads.  The S borrows contrast from both ends, where
# nothing is being judged, and gives it to the middle, where speckle lives.
# The cost is real and worth stating: the ends genuinely lose contrast, so a
# strong curve makes it harder to tell "just above noise" from "noise", and
# flattens the top of a bright specular target.  It is a display curve only -
# the beamformer, the dB meters, and the reverb readout never see it.
#
# It is NOT a substitute for getting the level right.  Fix dyn/gain first so
# tissue actually fills the window (a frame whose peak only reaches half grey
# is a level problem, and the curve will only stretch the noise with it), then
# reach for this.  ~0.55-0.70 is a sane working range.
# 0.65 (settings/latest.json 2026-08-15), inside the working range named above;
# 1.00 is the identity ramp this host drew before.
CURVE_DEF, CURVE_MIN = 0.65, 0.30

ZOOM_MIN, ZOOM_MAX = 1.0, 24.0

# The ring is bounded by BOTH of these, so raising the seconds alone does
# nothing once the byte ceiling binds - it just silently keeps fewer seconds.
# Cost is ~47 MB/s at 8 cm and rises with depth (the window grows faster than
# the frame rate falls), so 40 s needs:
#
#      4 cm  1.3 GB      16 cm  2.4 GB      40 cm  2.8 GB
#      8 cm  1.9 GB      30 cm  2.7 GB
#
# 2 GB buys the full 40 s out to ~10 cm and clamps beyond it rather than failing:
# ~39 s at the 14 cm startup depth, ~29 s at 16 cm, ~17 s at 40 cm.
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
def full_scale(apod=None, bank=None):
    a = APOD_DEF if apod is None else apod
    count = n_alive() if bank is None else max(1, int(alive_mask(bank).sum()))
    return float(count * 2048 * 2) * (1.0 - 0.5 * a)

# CPU twin of scurve() in the COMPRESS shader - see CURVE_DEF.  The M-mode
# strip greyscales itself in numpy rather than through the GL pipeline, and a
# strip drawn on a different transfer curve from the image above it is a lie,
# so both call their own copy of the same formula.  Keep them in step.
def scurve_np(v, p=None):
    p = float(state["curve"]) if p is None else float(p)
    if p >= 0.999:
        return v
    u = 2.0 * v - 1.0
    return 0.5 + 0.5 * np.sign(u) * np.power(np.abs(u), p)

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
# Current probe check: positions 25 and 46 are dead.  Keep both out of the
# coherent sum; raw RF is still retained, so this mask remains reversible.
#
# Override on the command line:  python tfm_gl_host.py dead=1,3,4
# or edit the box in the control row while running.
DEAD_DEF = "25,46"

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
    return max(1, int(alive_mask().sum()))

def alive_mask(bank=None):
    m = np.zeros(N_ELEM, dtype=np.float32)
    ctl = globals().get("pulser")
    if ctl is None:
        m[:] = 1
    elif ctl.single_elem is not None:
        m[ctl.single_elem] = 1
    else:
        m[:ctl.n_elem] = 1
    d = dead["set"]                 # one read: rebound, never mutated in place
    if d:
        m[sorted(d)] = 0.0
        if ctl is not None and ctl.shot_method == 2:
            m[[i ^ 1 for i in d]] = 0.0
    if bank is not None:
        m[BANK_FOR_ELEMENT != bank] = 0
    return m

def multi_rx_weights():
    # Normalize each transmitter over its usable receivers, including aperture edges.
    tx = np.arange(N_ELEM)[:, None]
    rx = tx + np.array(RX_OFFSETS)
    valid = (rx >= 0) & (rx < N_ELEM) & ~np.isin(rx, list(dead["set"]))
    weights = valid.astype(np.float32) * alive_mask()[:, None]
    # Reciprocal neighbor paths sample the same midpoint twice. Balance their
    # combined contribution against the center path at each full element pitch.
    weights[:, 0] *= 2.
    return weights / np.maximum(weights.sum(axis=1, keepdims=True), 1.)


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
# to the reference off the artifact itself.  Current RTL locks transmit launch
# to an ADC-grid marker, so residual motion should be far below the old ~2-sample
# error; keeping this alignment makes the subtraction tolerate what remains.
GATE_NEAR = 5
BG_AVG    = 16
level = {"near": -99.0, "far": -99.0}
bg    = {"ref": None, "acc": None, "first": None, "n": 0, "want": 0,
         "on": False}

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
# The RTL now fixes both original large terms: transmit launch waits for an
# ADC-grid toggle, and the range gate no longer waits for the USB/header FIFO.
# The phase marker still crosses through a two-flop synchronizer into the
# 100 MHz pulser domain, so a residual of roughly one 10 ns system-clock period
# is possible.  Analog propagation and marginal LVDS capture can add more.  The
# artifact measurement remains the direct way to distinguish that from motion.
#
# Correcting it needs a bg reference, and NOT the subtraction: the two are
# independent, so the checkbox is separate.
#
# MAXLAG is +/-8 samples = +/-200 ns, deliberately much wider than the expected
# residual.  If a shift rails at the limit the true peak is outside the window
# and the row is left uncorrected rather than dragged to a wrong answer.
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
# This bounds what the correction is good for.  Large transport faults are now
# rejected by the complete-sweep/tag checks; this path is for small residual
# timing error, not for trying to repair a torn acquisition.
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
    # Carrier period in samples.  The artifact IS the transmit burst, so its
    # carrier is the DRIVE frequency - not the receive band centre, which is
    # free to sit far from the drive (harmonic listening, noise hunting)
    # without silently mis-sizing the envelope smoothing and the alias gate
    # here.  measure_shifts runs on RAW rf, before the bandpass, so the
    # artifact keeps its drive-frequency carrier whatever the band says.
    try:
        f_car = float(pulser.f0_hz())
    except Exception:                   # replay with no pulser attached
        f_car = 0.0
    if not (2e5 < f_car < FS_HZ * 0.5):
        f_car = state["band_f0"] * 1e6
    per = FS_HZ / max(f_car, 1e5)
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

def _condition(rf, samps, live, bank=None):
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
    used = (multi_rx_weights().ravel() if pulser.shot_method == 3 else alive_mask()).astype(bool)
    rows = slice(None) if bank is None else list(BANKS[bank])
    if bank is not None:
        used = used[rows]
    m = rf[used] if used.any() else np.zeros((1, samps), np.float32)
    level["near"] = 20.0 * np.log10(float(np.abs(m[:, :g]).max()) / 2048.0 + 1e-12)
    level["far"]  = 20.0 * np.log10(
        float(np.sqrt(np.mean(np.square(m[:, g:])))) / 2048.0 + 1e-12)
    if live and bg["want"] > 0:
        ref_shape = rf.shape if bank is None else (N_ELEM, samps)
        if bg["acc"] is None or bg["acc"].shape != ref_shape:
            bg["acc"]   = np.zeros(ref_shape, dtype=rf.dtype)
            bg["first"] = np.zeros_like(bg["acc"])
            bg["counts"] = [0, 0]
            bg["n"]     = 0
        # ALIGN each sweep onto the first before averaging.  The whole point
        # of the reference is to measure capture-start jitter, and averaging
        # unaligned rows smears the artifact's carrier by that same jitter: at
        # 50 ns p-p the 16-sweep mean loses most of its carrier, live sweeps
        # then correlate below JIT_MINCORR against it, and de-jitter reports
        # used=0 - silently dead exactly when it is needed most.  Aligning to
        # the first sweep keeps the reference as sharp as a single sweep with
        # sqrt(BG_AVG) less noise, which is what the correlator wants.
        group = bank if bank is not None else 0
        if bank is None or bg["counts"][group] < BG_AVG:
            if bg["counts"][group] == 0:
                bg["first"][rows] = rf
                bg["acc"][rows] += rf
            else:
                s, ok, _ = measure_shifts(rf, bg["first"][rows], min(g, JIT_GATE))
                bg["acc"][rows] += _aligned_bg(rf, -s, ok)
            bg["counts"][group] += 1
            bg["n"]   += 1
            bg["want"] -= 1
        if bg["want"] == 0:
            bg["ref"], bg["acc"] = bg["acc"] / (BG_AVG if bank is not None else bg["n"]), None
            bg["first"] = None
    # One measurement, up to two consumers.  Skipped entirely when neither the
    # subtraction nor the correction wants it, so the default path is unchanged.
    ref  = bg["ref"]
    if ref is not None and bank is not None:
        ref = ref[rows]
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
MARK_C  = "#ff6f9c"         # cine in/out marks: not caliper yellow either

argv = [a.lower() for a in sys.argv[1:]]
mode = {"signed": any(a.startswith("sig") for a in argv)}
REPLAY_PATH = None
if "--replay" in sys.argv:
    replay_arg = sys.argv.index("--replay") + 1
    if replay_arg >= len(sys.argv) or sys.argv[replay_arg].startswith("--"):
        raise SystemExit("Usage: python host/tfm_gl_host.py --replay recording.rf.npz")
    REPLAY_PATH = sys.argv[replay_arg]
FORCE_SIM = any(a.startswith("sim") for a in argv) or REPLAY_PATH is not None
START_FAST17 = "--fast17" in argv
START_ARMED = "--arm" in argv
START_SETTINGS = None
if "--settings" in sys.argv:
    settings_arg = sys.argv.index("--settings") + 1
    if settings_arg >= len(sys.argv) or sys.argv[settings_arg].startswith("--"):
        raise SystemExit("Usage: python host/tfm_gl_host.py --settings preset.json [--arm]")
    START_SETTINGS = os.path.abspath(sys.argv[settings_arg])
if START_FAST17 and START_SETTINGS is not None:
    raise SystemExit("Use either --fast17 or --settings, not both")
if START_ARMED and not (START_FAST17 or START_SETTINGS is not None):
    raise SystemExit("--arm needs --fast17 or --settings preset.json")
if REPLAY_PATH is not None and (START_FAST17 or START_SETTINGS is not None or START_ARMED):
    raise SystemExit("Live startup flags cannot be combined with --replay")
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
         "dyn": float(DYN_DEF), "gain": float(GAIN_DEF), "auto": bool(AUTO_DEF),
         "curve": float(CURVE_DEF),
         "frozen": False, "depth_cm": DEPTH_CM_DEF,
         "band_on": bool(BAND_ON_DEF), "band_f0": float(BAND_F0_DEF),
         "band_bw": float(BAND_BW_DEF), "freq_comp": bool(FREQ_COMP_DEF),
         "jit": bool(JIT_ON_DEF),
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

def compound_band_edges():
    """Nominal non-overlap edges of the displayed frequency-compound bands."""
    lo, hi = band_edges()
    e = np.linspace(lo, hi, FREQ_COMP_BANDS + 1)
    return tuple((float(e[i]), float(e[i + 1])) for i in range(FREQ_COMP_BANDS))

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
    if debug_replay_only and not (((word >> 24) & 255) == 0x10 and (word & 1) == 0):
        return
    if debug_command_hook is not None:
        debug_command_hook(word, name)
    else:
        debug_startup_commands.append({"host_monotonic_s": time.perf_counter(),
                                       "name": name, "word_hex": f"{word:08x}"})
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

def us_to_cycles(us): return int(round(float(us) * CLK_HZ / 1_000_000))

afe_profile = recommended_profile()

def apply_afe_profile(profile=None):
    """Reapply the absolute low-noise CH1 receive profile while disarmed."""
    global afe_profile
    requested = recommended_profile() if profile is None else dict(profile)
    writes = register_writes(requested)  # validate before changing live state
    afe_profile = requested
    for addr, value in writes:
        send_cmd(cmd(OP_AFE_REG, (addr << 16) | value), f"afe_{addr:02x}")
        # afe5804_ctrl has a one-entry request latch.  One SPI transaction is
        # about 30 us; 1 ms prevents a later absolute write replacing it.
        if HW:
            time.sleep(.001)

# --- the pulser's receive window must cover ours ------------------------------
# The transmit sequencer runs on its OWN timebase: it fires the next element
# t_settle + burst + (t_ring + t_rx) later regardless of what the capture side
# is doing.  The depth slider only ever resized the CAPTURE window, so the two
# drifted apart, with two distinct failure modes:
#
#   capture cycle (dly + win + gap) > element period
#       -> the sequencer is still in S_DAMP when the next tx_sync arrives, that
#          burst is ignored, and the frame rate halves.  Harmless but slow; at
#          8 cm this was already happening (159 us vs 139 us).
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

# ...and the startup values this host wants on top of those, from
# settings/latest.json 2026-08-15.  Set here rather than in pulser_ctrl.DEFAULTS
# because that dict IS the shared part: tfm_host.py reads the same one, and its
# plain-burst default should stay plain.  These are only attribute writes - no
# command goes out - so push_all() below (or the panel, without hardware) sends
# them exactly as if the sliders had been dragged there by hand.
#
# A 5.2 -> 2.6 MHz DOWN-sweep in 1 us: short enough that the compressed pulse is
# barely longer than the plain burst, swept downward so the low end - which the
# probe passes best and tissue attenuates least - arrives last and comes back
# from depth.  Tick "chirp" off for the stock n_cycles burst.
pulser.chirp_on     = True
pulser.chirp_f0_mhz = 5.2
pulser.chirp_f1_mhz = 2.6
pulser.chirp_us     = 1.0
pulser.arm = False            # configure first; PULSER RUN explicitly starts a debug run

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

def send_seq_config(lo, hi, dly_us, gap_us, reach_pct=100):
    """Push the full sequencer timing/TGC setup for the current window length."""
    inc = tgc_increment(lo, hi, cfg["win_words"], reach_pct)
    send_cmd(cmd(OP_SEQ_LEN, cfg["win_words"]), "seq_len")
    send_cmd(cmd(OP_SEQ_DLY, us_to_cycles(dly_us)), "seq_dly")
    send_cmd(cmd(OP_SEQ_GAP, us_to_cycles(gap_us)), "seq_gap")
    send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
    send_cmd(cmd(OP_SEQ_TGC1, hi), "seq_tgc1")
    send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")
    send_pls_rx(dly_us, gap_us)

bufs = views = ovs = got = None
if HW:
    d3.FT_SetPipeTimeout(h, C.c_ubyte(PIPE_OUT), C.c_ulong(1000))
    print("locking RX window (0xA5A55A5A)...")
    send_cmd(LOCK_WORD, "lock")
    time.sleep(0.05)
    send_cmd(cmd(0x10, 0), "startup_disarm")
    apply_afe_profile()
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
golay_pairs = GolayPairs()
three_rx_groups = ThreeRxGroups()
raw_buf = np.zeros((N_ELEM, cfg["samps"]), dtype=np.int16)  # sweep being assembled
live_buf = np.zeros_like(raw_buf)                            # last complete sweep
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
         "complete_sweeps": 0, "win_sweeps": 0, "sweep_hz": 0.0,
         "seq_bad": 0, "seq_chk": 0,
         "skips": 0, "bad_sweeps": 0,
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
        replay["rf"] = rf.copy()  # detach cine slots and retain the physical aperture
    hil_ev.set()

def publish_replay_sync(rf):
    """Same transform, run on the CALLING thread and published immediately.

    Scrubbing wants the asynchronous path - the UI must not block on an FFT.
    The video exporter wants the opposite: it has to know the texture holds
    frame k before it grabs frame k, and 'ask the worker and hope' would race
    every frame.  Same _condition + analytic as the worker, so an exported
    frame is bit-identical to the scrubbed one."""
    samps = cfg["samps"]
    out = prepare_analytic(rf, samps, live=False)
    with hil_lk:
        hil.update(data=out, samps=samps, gen=hil["gen"] + 1)

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
        self.quality = collections.deque()
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
            self.quality.clear()
            self.free.clear()
            self.shape = None

    def push(self, src, quality=None):
        """One completed sweep.  Called from the reader thread with buf_lk held,
        so it has to stay cheap - one ~0.1 ms copy into a recycled slot."""
        if not self.recording:
            return
        t = time.perf_counter()
        with self.lk:
            if not self.recording:
                return
            if self.shape != tuple(src.shape):      # depth changed under us
                self.buf.clear(); self.free.clear()
                self.quality.clear()
                self._configure(src.shape)
            while self.buf and (len(self.buf) >= self.cap or
                                t - self.buf[0][0] > CINE_SECONDS):
                self.free.append(self.buf.popleft()[1])
                self.quality.popleft()
            a = self.free.pop() if self.free else np.empty(self.shape, np.int16)
            np.copyto(a, src)
            self.buf.append((t, a))
            self.quality.append(quality or {"valid": True, "valid_elements": list(range(N_ELEM)),
                                            "source": "simulation"})

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
live_bank = None            # published with live_buf under buf_lk
_sweep_seen = np.zeros(N_ELEM, dtype=bool)
_sweep_bad = np.zeros(N_ELEM, dtype=bool)
_sweep_fcnt = np.full(N_ELEM, -1, dtype=np.int64)
_sweep_ok = True
# FAIL OPEN.  Rejecting damaged sweeps is right while most sweeps are clean,
# but an all-or-nothing gate turns any PERSISTENT defect (one repeatedly
# skipped element, a recurring tag hole, a misbehaving new bitstream) into a
# fully black screen with no image to debug against.  A degraded picture with
# the `rejected` counter climbing tells you what is wrong; black tells you
# nothing.  After REJECT_MAX consecutive rejects the sweep is published
# anyway, with missing rows zeroed and quality flags retained for export.
# It still counts in bad_sweeps.
REJECT_MAX = 8              # consecutive rejects before publishing regardless
_rej_run = 0

def seq_check(raw16):
    """Look for holes INSIDE a receive window.

    afe_stream.v tags every 12-bit sample with a 4-bit rolling counter in the
    top nibble, and when the ADC FIFO backs up it drops whole sample pairs
    SILENTLY (afe_stream.v: `wpush <= !wfull`).  That FIFO is now 4096 words
    deep - about 205 us of slack - but a longer stall can still punch a time
    hole into the middle of a trace.

    The frame still arrives with the right length and the right header, so
    frame_count stays continuous and 'drops' stays at zero.  The sequence tag
    is the ONLY evidence.  The signature is distinctive: everything before the
    hole is at the correct depth, everything after it is shifted, and the shift
    changes from frame to frame - i.e. flickering dark patches deeper in the
    window while the surface echo stays put.

    Every frame is checked.  The returned mask lets batch() reject the whole
    sweep containing a damaged row; displaying it would put every sample after
    the hole at the wrong depth and destroy phase coherence."""
    if raw16.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    t = (raw16 >> 12).astype(np.int16)           # tag counts +1 per SAMPLE
    d = np.diff(t, axis=1)
    bad = (d != 1) & (d != -15)
    stats["seq_bad"] += int(np.count_nonzero(bad))
    stats["seq_chk"] += raw16.shape[0]
    return np.any(bad, axis=1)

def batch(fr):
    """fr: (m, frame_words) uint32, all rows verified to start with a header."""
    global _prev_elem, _sweep_ok, _rej_run, live_bank
    hdr   = fr[:, 0]
    elems = ((hdr >> 16) & ELEM_MASK).astype(np.int32)
    fcnt  = (hdr & 0xFFFF).astype(np.int64)
    counter_bad = np.zeros(len(fcnt), dtype=bool)
    if stats["last_fcnt"] is not None:
        counter_bad[0] = ((int(fcnt[0]) - stats["last_fcnt"]) & 0xFFFF) != 1
    counter_bad[1:] = (np.diff(fcnt) & 0xFFFF) != 1
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
    sparse = pulser.shot_method == ALTERNATING_24
    if sparse:
        ids = np.r_[_prev_elem, elems] if _prev_elem >= 0 else elems
        slots = SLOT_FOR_ELEMENT[ids]
        groups = BANK_FOR_ELEMENT[ids]
        # The current fixed group wraps every 24 shots. The cross-group path
        # remains for streams made by the earlier alternating implementation.
        de = np.where(groups[1:] == groups[:-1],
                      np.diff(slots % 24) % 24,
                      np.diff(slots) % N_ELEM)
    else:
        de = np.diff(elems)
    stats["skips"] += int(np.sum(de[de > 1] - 1))

    raw16 = np.ascontiguousarray(fr[:, 1:]).view(np.uint16)
    bad_rows = seq_check(raw16) | counter_bad
    u = (raw16 & 0x0FFF).astype(np.int32)
    c = np.where(u >= 2048, u - 4096, u) if mode["signed"] else u - 2048
    c = c.astype(np.int16)
    if pulser.shot_method in (1, 3):
        assembler = golay_pairs if pulser.shot_method == 1 else three_rx_groups
        elems, fcnt, c, bad_rows = assembler.unpack((hdr >> 22) & 3, elems, fcnt, c, bad_rows)
        if not elems.size:
            return
    keep = elems < N_ELEM                   # ignore ids the array cannot hold

    # Build one sweep in raw_buf, then copy it into live_buf only at a verified
    # element-id wrap.  The old path woke the Hilbert worker at the end of every
    # USB batch, when raw_buf usually held the tail of one sweep and stale rows
    # from the previous one.  A skipped element made the stale row persist for
    # a whole sweep.  Both cases are phase-incoherent and look like boiling,
    # horizontal jitter and spotty coherence-factor dropouts.
    #
    # A USB batch spans several sweeps, so keep the row copies vectorized within
    # each no-wrap segment.  cine receives every clean sweep; live_buf keeps the
    # newest one for the display worker.
    wraps = np.nonzero(np.diff(np.concatenate(([_prev_elem], elems))) <= 0)[0]
    if sparse:
        # Finish on the last physical shot, even at a USB transfer boundary.
        # A wrap also closes a damaged/truncated group so we can resynchronize.
        ends = np.flatnonzero((elems == BANKS[0][-1]) | (elems == BANKS[1][-1])) + 1
        wraps = np.union1d(wraps, ends)
    lo = 0
    published = False

    def ingest(a, b):
        global _sweep_ok
        if b <= a:
            return
        good_id = keep[a:b]
        if np.any(~good_id):
            _sweep_ok = False
        rr = elems[a:b][good_id]
        if rr.size == 0:
            return
        # Existing rows mean a duplicate id; duplicates inside rr need the
        # unique test because boolean advanced indexing observes the old mask.
        if np.any(_sweep_seen[rr]) or np.unique(rr).size != rr.size:
            _sweep_ok = False
        if np.any(bad_rows[a:b][good_id]):
            _sweep_ok = False
        raw_buf[rr] = c[a:b][good_id]
        _sweep_seen[rr] = True
        _sweep_bad[rr] |= bad_rows[a:b][good_id]
        _sweep_fcnt[rr] = fcnt[a:b][good_id]

    for w in wraps:
        w = int(w)
        ingest(lo, w)
        lo = w
        if not _sweep_seen.any():
            continue
        expected = ([pulser.single_elem] if pulser.single_elem is not None else list(range(pulser.n_elem)))
        bank = None
        if sparse:
            bank = int(BANK_FOR_ELEMENT[np.flatnonzero(_sweep_seen)[0]])
            expected = list(BANKS[bank])
            _sweep_ok &= _sweep_seen.sum() == len(expected)
        complete = _sweep_ok and bool(np.all(_sweep_seen[expected]))
        quality = {"valid": bool(complete),
                   "valid_elements": np.flatnonzero(_sweep_seen & ~_sweep_bad).tolist(),
                   "missing_elements": [e for e in expected if not _sweep_seen[e]],
                   "bad_elements": np.flatnonzero(_sweep_bad).tolist(),
                   "element_frame_counters": _sweep_fcnt.tolist(),
                   "transport_counters": {k: int(stats[k]) for k in
                       ("drops", "resyncs", "seq_bad", "seq_chk", "skips", "bad_sweeps")}}
        if complete:
            live_bank = bank
            if sparse:
                quality["bank"] = bank
            stats['complete_sweeps'] += 1
            stats['win_sweeps'] += 1
            np.copyto(live_buf, raw_buf)
            cine.push(raw_buf, quality)
            published = True
            _rej_run = 0
        elif bool(np.any(_sweep_seen)):
            stats["bad_sweeps"] += 1
            _rej_run += 1
            if _rej_run >= REJECT_MAX and pulser.shot_method not in (1, 3, ALTERNATING_24):
                np.copyto(live_buf, raw_buf)
                cine.push(raw_buf, quality)
                published = True
                _rej_run = 0
        _sweep_seen.fill(False)
        _sweep_bad.fill(False)
        _sweep_fcnt.fill(-1)
        raw_buf.fill(0)            # absent rows must never masquerade as current RF
        _sweep_ok = True
    ingest(lo, elems.size)
    _prev_elem = int(elems[-1])

    stats["frames"]     += fr.shape[0]
    stats["win_frames"] += fr.shape[0]
    if published:
        stats["dirty"] = True
        hil_ev.set()

def valid_headers(words):
    kind = (words >> 22) & 3
    if pulser.shot_method == 3:
        return ((words >> 24) == 0xe2) & (kind < 3) & (((words >> 16) & ELEM_MASK) < N_ELEM)
    if pulser.shot_method == 1:
        valid = (kind == 1) | (kind == 2)
    else:
        valid = kind == (3 if pulser.shot_method == 2 else 0)
    return ((words >> 24) == 0xe1) & valid & (((words >> 16) & ELEM_MASK) < N_ELEM)


def process(words):
    """Frame parser.  Fast path: back-to-back aligned frames, fully vectorized.
    A header is 0xE1 in the top byte with the guard bits above the element
    field zero -> (word >> HDR_SHIFT) == HDR_MAGIC."""
    global carry, debug_discard_words
    consumer = debug_probe_consumer
    if consumer is not None:
        consumer(words)
        return
    with buf_lk:
        if debug_replay_only or debug_discard_words == -1:
            return
        if debug_discard_words > 0:
            skip = min(words.size, debug_discard_words)
            debug_discard_words -= skip
            words = words[skip:]
            carry = np.empty(0, np.uint32)
            if not words.size:
                return
        FW = cfg["frame_words"]
        w = np.concatenate((carry, words)) if carry.size else words
        pos, n = 0, w.size
        while n - pos >= FW:
            nfr  = (n - pos) // FW
            hdrs = w[pos : pos + nfr*FW : FW]
            ok   = valid_headers(hdrs)
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
                    nxt = np.nonzero(valid_headers(w[pos+1:]))[0]
                    if nxt.size == 0:
                        pos = n
                        break
                    pos += 1 + int(nxt[0])
        carry = w[pos:].copy()                      # partial frame -> next chunk

def reader():
    n = C.c_ulong(0)
    while stats["alive"]:
        for i in range(NBUF):
            n.value = 0
            result = d3.FT_GetOverlappedResult(h, C.byref(ovs[i]), C.byref(n), C.c_int(1))
            if not stats["alive"]:
                return
            if result == 19:  # a disarmed pulser produces no SRC_SEQ data
                stats["read_timeouts"] = stats.get("read_timeouts", 0) + 1
                # Discarded partial bytes make the next sweep discontinuous.
                stats["timeout_bytes_discarded"] = stats.get("timeout_bytes_discarded", 0) + n.value
                queue(i)
                continue
            if result != FT_OK:
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
            stats['sweep_hz'] = stats['win_sweeps'] / dt
            stats['win_sweeps'] = 0
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
    global live_bank
    scat = [(0.000, 0.020), (0.010, 0.034), (-0.013, 0.048),
            (0.005, 0.062), (-0.004, 0.013), (0.017, 0.075)]
    _R  = PROBE_R_MM * 1e-3
    _th = (np.arange(N_ELEM) - (N_ELEM - 1) / 2.0) * (PITCH_MM / PROBE_R_MM)
    tx  = (_R * np.sin(_th)).astype(np.float32)
    tz  = (_R * (np.cos(_th) - 1.0)).astype(np.float32)
    while stats["alive"]:
        if debug_replay_only or debug_discard_words == -1:
            time.sleep(0.03)
            continue
        with buf_lk:
            samps, c = cfg["samps"], state["c"]
            method = pulser.shot_method
        t = (np.arange(samps, dtype=np.float32) / FS_HZ)[None, :]
        offsets = RX_OFFSETS if method == 3 else (0,)
        a = np.zeros((N_ELEM, len(offsets), samps), np.float32)
        dly_s = state["dly_us"] * 1e-6
        for (sx, sz) in scat:
            d   = np.hypot(sx - tx, sz - tz).astype(np.float32)
            for slot, offset in enumerate(offsets):
                ids = np.arange(N_ELEM) ^ 1 if method == 2 else np.arange(N_ELEM) + offset
                path = d + d[np.clip(ids, 0, N_ELEM-1)]
                dt = t - (path / c - dly_s)[:,None]
                a[:,slot,:] += 900.0 * np.exp(-(dt / 2.5e-7) ** 2) * np.cos(2*np.pi*5e6 * dt)
        a = a.reshape(N_ELEM, -1)
        if method == 1:
            members = [np.zeros_like(a), np.zeros_like(a)]
            for i, signs in enumerate(zip(*GOLAY_CODES)):
                delay = i * golay_chip_samples()
                lag = int(delay)
                for shift, weight in ((lag, 1 - (delay - lag)), (lag + 1, delay - lag)):
                    if shift >= samps or weight == 0:
                        continue
                    for member, sign in zip(members, signs):
                        member[:,shift:] += sign * weight * a[:,:samps-shift]
            a = np.concatenate(members, axis=1)
        a += np.random.normal(0.0, 35.0, a.shape).astype(np.float32)
        if method == 3:
            a[0,samps:2*samps] = 0
            a[-1,2*samps:] = 0
        with buf_lk:
            if cfg["samps"] == samps and pulser.shot_method == method and raw_buf.shape == a.shape:
                raw_buf[:] = np.clip(a, -2048, 2047).astype(np.int16)
                quality = None
                shots = shots_per_sweep(method, pulser.n_elem, pulser.single_elem)
                if method == ALTERNATING_24:
                    live_bank = 0
                    raw_buf[BANK_FOR_ELEMENT != live_bank] = 0
                    quality = {"valid": True, "bank": live_bank, "source": "simulation",
                               "valid_elements": list(BANKS[live_bank])}
                np.copyto(live_buf, raw_buf)
                cine.push(raw_buf, quality)
                stats["dirty"] = True
                hil_ev.set()
                stats["frames"] += shots
                stats["win_frames"] += shots
                stats['complete_sweeps'] += 1
                stats['win_sweeps'] += 1
                stats["bytes"] += samps * 2 * shots
                stats["win_bytes"] += samps * 2 * shots
        dt_w = time.perf_counter() - stats["t0"]
        if dt_w >= 0.5:
            stats["mbps"] = stats["win_bytes"] / dt_w / 1e6
            stats["fps"]  = stats["win_frames"] / dt_w
            stats['sweep_hz'] = stats['win_sweeps'] / dt_w
            stats['win_sweeps'] = 0
            stats["win_bytes"], stats["win_frames"] = 0, 0
            stats["t0"] = time.perf_counter()
        time.sleep(1.0 / 30.0)

reader_thread = threading.Thread(target=reader if HW else sim_reader, daemon=True)
reader_thread.start()

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
    """Analytic RF -> (npts,) envelope along the segment a..b.

    A normal frame is (N, samps, 2).  Frequency compounding publishes
    (bands, N, samps, 2); each band is beamformed with the same delays and the
    detected powers are summed, exactly like the fragment shader.

    Transcription of the BEAMFORM fragment shader; see the note above."""
    if an.ndim == 4:
        if an.shape[0] != FREQ_COMP_BANDS:
            raise ValueError("frequency-compound frame has %d bands, expected %d"
                             % (an.shape[0], FREQ_COMP_BANDS))
        power = np.zeros(npts, np.float32)
        for band in an:
            mag = mline_sample(band, samps, a, b, npts)
            power += mag * mag
        return np.sqrt(power).astype(np.float32)
    if an.ndim != 3:
        raise ValueError("analytic RF must have 3 or 4 dimensions")

    E     = elem_uniform()                              # (N,4) x, z, nx, nz
    alive = alive_mask()                                # (N,)
    f     = np.linspace(0.0, 1.0, npts, dtype=np.float32)
    px    = a[0] + (b[0] - a[0]) * f
    pz    = a[1] + (b[1] - a[1]) * f

    dvx = px[:, None] - E[None, :, 0]                   # (M,N)
    dvz = pz[:, None] - E[None, :, 1]
    d   = np.hypot(dvx, dvz)
    ds  = np.maximum(d, 1e-9)

    bank = getattr(an, 'bank', None)
    tx = np.arange(N_ELEM) if bank is None else np.asarray(BANKS[bank])
    if an.shape[0] == 3 * N_ELEM:
        rx = np.clip(tx[:,None] + np.array(RX_OFFSETS), 0, N_ELEM-1).ravel()
        tx = np.repeat(tx, 3)
        row_weight = multi_rx_weights().ravel()
    else:
        rx = tx ^ 1 if pulser.shot_method == 2 else tx
        row_weight = alive[tx]
    paths = d[:,tx] + d[:,rx]
    t = (paths / state["c"] + state["t0_ns"] * 1e-9 - state["dly_us"] * 1e-6) * FS_HZ
    normals = (dvx * E[None,:,2] + dvz * E[None,:,3]) / ds
    cosa = np.minimum(normals[:,tx], normals[:,rx])
    cacc = float(np.cos(np.radians(state["accept"])))
    ok   = ((t >= 0.0) & (t <= samps - 1.0) & (cosa >= cacc) &
            (row_weight[None, :] > 0))

    ap = max(state["apod"], 1e-4)
    v  = np.abs(2.0 * (tx.astype(np.float32) / (N_ELEM - 1.0)) - 1.0)
    w  = (_ramp((1.0 - v) / ap)[None, :] *
          _ramp(((cosa - cacc) / max(1.0 - cacc, 1e-6)) / ap))
    w  = np.where(ok, w * row_weight, 0.0).astype(np.float32)

    # Fractional-delay tap, the CPU's version of the shader's bilinear fetch.
    # Flatten to (N*samps, 2) and gather with take(): 2-D fancy indexing on the
    # (N, samps, 2) array costs ~60% more, and this runs inside the per-sweep
    # budget so it is worth the extra line.
    ti   = np.clip(t, 0.0, samps - 2.0)
    i0   = ti.astype(np.int32)
    fr   = (ti - i0)[..., None].astype(np.float32)
    rows = len(tx)
    flat = an.reshape(rows * samps, 2)
    k    = (np.arange(rows, dtype=np.int64) * samps + i0).ravel()
    s    = (flat.take(k, axis=0).reshape(npts, rows, 2) * (1.0 - fr) +
            flat.take(k + 1, axis=0).reshape(npts, rows, 2) * fr)   # (M,N,2)

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

def golay_chip_samples():
    return 2 * (pls_ns_to_cyc(pulser.t_drive_ns) + pls_ns_to_cyc(pulser.t_dead_ns)) * FS_HZ / CLK_HZ


def prepare_analytic(rf, samps, live=False):
    with pipeline_lock:
        if rf.shape[1] != samps * windows_per_tx(pulser.shot_method):
            raise ValueError("RF window length does not match the acquisition method")
        if pulser.shot_method == 3:
            rf = rf.reshape(N_ELEM * 3, samps)
        if pulser.shot_method == 1:
            rf = decode_golay(rf, golay_chip_samples())
        if pulser.shot_method == ALTERNATING_24:
            bank = getattr(rf, 'bank', None)
            if bank not in (0, 1):
                raise ValueError("Sparse RF is missing its aperture group")
            selected = np.asarray(rf)[list(BANKS[bank])].astype(np.float32)
            cond, sh = _condition(selected, samps, live, bank)
            return BankFrame(analytic(cond, samps, sh), bank)
        cond, sh = _condition(np.asarray(rf, dtype=np.float32), samps, live=live)
        return analytic(cond, samps, sh)


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
            samps = cfg["samps"]
            t0 = time.perf_counter()
            with pipeline_lock:
                if (rep.shape != live_buf.shape or
                        isinstance(rep, BankFrame) != (pulser.shot_method == ALTERNATING_24)):
                    continue
                samps = cfg["samps"]
                out = prepare_analytic(rep, samps, live=False)
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
            source = live_buf
            rf = source.copy()          # immutable, complete 48-element sweep
            bank = live_bank if pulser.shot_method == ALTERNATING_24 else None
        # Averaging goes here, not in the reader: the copy above is already off
        # the USB path, and the cine ring keeps storing RAW sweeps so a recorded
        # loop can be re-averaged (or not) at replay time.
        t0 = time.perf_counter()
        with pipeline_lock:
            if source is not live_buf or samps != cfg["samps"]:
                continue
            sample = BankFrame(rf, bank) if bank is not None else rf_avg.push(rf)
            out = prepare_analytic(sample, samps, live=True)
        perf["hil_ms"] = (time.perf_counter() - t0) * 1e3
        if state["frozen"]:             # froze mid-transform: do not stomp the
            continue                    # frame the user just paused on
        # Live sweeps only.  A replayed frame would push a column stamped with
        # the wall clock rather than its acquisition time, so scrubbing the cine
        # loop would shuffle the strip's time axis into nonsense.
        a, b = mline["a"], mline["b"]
        if mline["on"] and a is not None and b is not None:
            try:
                column = mline_sample(out, samps, a, b)
                if bank is not None:
                    column *= full_scale() / full_scale(bank=bank)
                mm_push(column)
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

def _compound_hilb_masks(nfft, lo_hz, hi_hz):
    """Three power-complementary sub-band masks over the normal Hilbert mask.

    At each FFT bin sum(mask[b]**2) equals base_mask**2 (within float error),
    including the raised-cosine outer passband.  The GPU can therefore sum the
    independently beamformed band powers without a brightness correction.
    Narrow sin/cos crossfades avoid the time ringing a hard spectral cut would
    create while keeping neighbouring bands mostly decorrelated."""
    base = _hilb_mask(nfft, lo_hz, hi_hz)
    f    = np.arange(nfft, dtype=np.float64) * (FS_HZ / nfft)
    cuts = np.linspace(lo_hz, hi_hz, FREQ_COMP_BANDS + 1)[1:-1]
    span = max(float(hi_hz - lo_hz), 1.0)
    xf   = max(span * FREQ_COMP_XFADE, FS_HZ / nfft)

    # Start as hard, non-overlapping partitions, then replace a narrow region
    # around each seam with a cos/sin power-complementary crossfade.
    q = np.zeros((FREQ_COMP_BANDS, nfft), dtype=np.float64)
    which = np.searchsorted(cuts, f, side="right")
    q[which, np.arange(nfft)] = 1.0
    for i, cut in enumerate(cuts):
        x = (f - (cut - 0.5 * xf)) / xf
        m = (x > 0.0) & (x < 1.0)
        th = 0.5 * np.pi * x[m]
        q[i,     m] = np.cos(th)
        q[i + 1, m] = np.sin(th)
    return (q * base[None, :]).astype(np.float32)

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
    if recorded_tx_reference is not None:
        _mf_ref["gen"] = ("recording", id(recorded_tx_reference))
        return recorded_tx_reference
    if _mf_ref["gen"] != pulser.tx_gen:
        _mf_ref.update(gen=pulser.tx_gen,
                       ref=np.asarray(pulser.tx_waveform(FS_HZ),
                                      dtype=np.float32))
    return _mf_ref["ref"]

# --- what the pulser is ACTUALLY transmitting ---------------------------------
# The chirp sliders are a request, not a readout.  Every switching edge is
# rounded onto the 100 MHz clock grid (chirp_edges_cyc), so the frequency that
# comes out is only ever an approximation of the one asked for, and the
# approximation coarsens with frequency: a half period at 2 MHz is 25 clock
# cycles and rounds to 0.2%, at 7 MHz it is 7.1 cycles and rounds to 1.3%.
# f0_hz() does not help for a chirp - it returns the arithmetic mean of the two
# sliders and never looks at the waveform at all.
#
# So measure it: FFT the same quantised waveform mf_reference() hands the
# matched filter.  That array IS the commanded drive, edge for edge.
#
# Two things this deliberately is not.
#
#   * It is the DRIVE, not the FIELD.  The transducer's two-way response
#     multiplies it and is measured nowhere in this host, so a line that looks
#     perfectly healthy here radiates nothing whatever if it sits outside the
#     probe's band.  That is what tx_in_probe_band is for, and why it is on the
#     same readout rather than buried somewhere else.
#   * The drive is hard-switched +/-1, so it carries the odd harmonics of a
#     square wave.  The third is at -9.5 dB - comfortably under the -6 dB edges
#     below, so it cannot widen them, but it holds a ninth of the power and
#     WOULD drag a whole-spectrum centroid upwards by a good fraction of a
#     megahertz.  Hence the centroid is taken over the -6 dB support only.
#
# The -6 dB edges are the useful pair for a chirp (they span the sweep); the
# peak is the useful single number for a fixed burst.  Both are reported
# because which one is meaningful depends on a mode the reader can see anyway.
_tx_spec = {"gen": None, "freq": None, "pwr": None, "val": None}
def _tx_spec_now():
    """Cached (freq_mhz, power, (peak, mid, lo, hi)) for the commanded drive.

    Keyed on pulser.tx_gen - the counter the pulser bumps on any transmit-shape
    command - so this rebuilds when the burst moves and never on a frame."""
    ref = mf_reference()
    reference_key = _mf_ref["gen"]
    if _tx_spec["gen"] != reference_key:
        # Pad hard.  A 1 us burst puts raw bins 1 MHz apart, which is coarser
        # than the -6 dB width being measured; 8x padding interpolates the lobe
        # finely enough that the edges stop stepping as the sliders move.
        n    = max(4096, 1 << int(np.ceil(np.log2(max(len(ref), 2) * 8))))
        mag  = np.abs(np.fft.rfft(ref, n))
        freq = np.fft.rfftfreq(n, 1.0 / FS_HZ) / 1e6
        # Skip DC: an unbalanced burst (odd half-cycle count) has a baseline
        # term that is not a frequency and must not win the peak search.
        g    = int(np.searchsorted(freq, 0.2))
        pk   = g + int(np.argmax(mag[g:]))
        idx  = np.flatnonzero(mag >= 0.5 * mag[pk])     # -6 dB
        idx  = idx[idx >= g]
        if idx.size == 0:                               # cannot happen; cheap
            idx = np.array([pk])
        # Outermost crossings, not the contiguous run: a chirp's passband
        # ripples and dips below half a few times across the sweep, and the
        # span is what matters, not the first dropout.
        lo, hi = float(freq[idx[0]]), float(freq[idx[-1]])
        p      = mag[idx].astype(np.float64) ** 2
        mid    = float((freq[idx] * p).sum() / max(p.sum(), 1e-30))
        _tx_spec.update(gen=reference_key, freq=freq,
                        pwr=mag.astype(np.float64) ** 2,
                        val=(float(freq[pk]), mid, lo, hi))
    return _tx_spec

def tx_spectrum():
    """(peak, mid, lo, hi) of the commanded drive in MHz; lo/hi are -6 dB."""
    return _tx_spec_now()["val"]

def tx_in_probe_band():
    """Fraction of commanded drive energy landing inside the probe's passband.

    Reads as a headroom figure, not a score: a hard-switched square drive keeps
    only 8/pi^2 = 81% of its energy in the fundamental however well it is
    placed, so ~0.8 is the practical ceiling and anything near it is fine.  It
    is the low readings that carry the information - 0.2 means four fifths of
    the drive is going somewhere the transducer cannot radiate it."""
    d = _tx_spec_now()
    m = (d["freq"] >= PROBE_LO_MHZ) & (d["freq"] <= PROBE_HI_MHZ)
    return float(d["pwr"][m].sum() / max(d["pwr"].sum(), 1e-30))

_hilb = {"key": None, "wgt": None}
def analytic(rf, samps, shifts=None):
    """Real RF -> float32 analytic signal(s), interleaved re/im.

    Normal output is (N, samps, 2).  With frequency compounding enabled it is
    (FREQ_COMP_BANDS, N, samps, 2): one independently filtered analytic frame
    per power-complementary receive sub-band.

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
    comp = state["freq_comp"] and state.get("debug_view", 0) == 0
    ref  = mf_reference() if mf else None
    if mf and pulser.shot_method == 1:
        ref = ref[:max(1, round(golay_chip_samples()))]
    nfft = next_fast_len(samps + (ref.size if mf else 0))
    lo, hi = band_edges()
    key  = (nfft, mf, _mf_ref["gen"] if mf else None, comp, lo, hi)
    if _hilb["key"] != key:            # the UI thread moves the settings, and
        wgt = (_compound_hilb_masks(nfft, lo, hi) if comp
               else _hilb_mask(nfft, lo, hi))
        if mf:
            # Divide by the reference energy so a perfect echo compresses to
            # its own amplitude rather than to (amplitude * sum ref^2) - the
            # brightness scale stays comparable when the checkbox is toggled.
            R   = np.fft.fft(ref.astype(np.float64), nfft)
            corr = np.conj(R) / max(float(np.dot(ref, ref)), 1e-9)
            wgt = (wgt * (corr[None, :] if wgt.ndim == 2 else corr)
                   ).astype(np.complex64)
        _hilb.update(key=key, wgt=wgt)
    if shifts is not None:
        k0, j = _split_shift(-np.asarray(shifts, dtype=np.float64))
        if np.any(k0):
            rf = _roll_rows(rf, k0)
    X = _fft(rf, n=nfft, axis=1, **_FFT_KW)
    if shifts is not None:
        # Per-element, so it cannot broadcast; the loop avoids materialising a
        # (48, nfft) gather, which at 30 cm would be 6 MB of traffic per frame.
        # The mask has already zeroed k > nfft/2, so the ramp only has to be
        # correct on the positive half - which it is, by construction.
        tbl = _frac_ramps(nfft)
        for i in range(X.shape[0]):
            if j[i]:
                X[i] *= tbl[j[i]]
    if comp:
        # One forward FFT, then one inverse transform per sub-band.  The leading
        # dimension is intentionally kept through the hand-off so detection and
        # power summation happen AFTER beamforming, where speckle decorrelates.
        Y  = X[None, :, :] * _hilb["wgt"][:, None, :]
        an = _ifft(Y, axis=2, **_FFT_KW)[:, :, :samps]
    else:
        X *= _hilb["wgt"]
        an = _ifft(X, axis=1, **_FFT_KW)[:, :samps]
    out = np.empty(an.shape + (2,), dtype=np.float32)
    out[..., 0] = an.real
    out[..., 1] = an.imag
    return out

hilbert_thread = threading.Thread(target=hilbert_worker, daemon=True)
hilbert_thread.start()

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

uniform sampler2D rf0;         // RG32F, width = samps, height = N (re, im)
uniform sampler2D rf1;         // frequency-compound bands 2 and 3; rf0 only when off
uniform sampler2D rf2;
uniform vec4  elems[%(N)d];    // (x, z, nx, nz): position m, outward normal
uniform vec4  viewbox;         // x0, x1, z0, z1 in metres
uniform float c, dly_s, fs;    // sound speed m/s, pulse->rx delay s, sample rate
uniform float samps;           // valid samples per A-scan == texture width
uniform float cos_acc;         // cos(acceptance half-angle)
uniform float apod;            // Tukey fraction, 0 = rect, 1 = full Hann
uniform float t0_s;            // fixed lens/electronic round-trip offset
uniform int neighbor_rx;
uniform int multi_rx;
uniform int alternating;
uniform vec3 rx_weights[%(N)d];
uniform float alive[%(N)d];    // 0 = dead element, excluded from the sum
uniform float cf_pow;          // coherence-factor exponent, 0 = off
uniform float freq_comp;       // 1 = RSS of three independently beamformed bands
uniform int debug_view;        // 0 weighted, 1 ordinary DAS, 2 coherence map

// Half-Hann ramp: 0 at v = 0, 1 at v >= 1, flat slope at both ends so the
// weight has no corner to ring on.
float ramp(float v) { return 0.5 - 0.5 * cos(3.14159265 * clamp(v, 0.0, 1.0)); }

void main() {
    vec2 p = vec2(mix(viewbox.x, viewbox.y, v_uv.x),
                  mix(viewbox.z, viewbox.w, 1.0 - v_uv.y));
    vec2  acc  = vec2(0.0);     // coherent (complex) sum - the image
    vec2  acc1 = vec2(0.0);     // the two extra frequency-compound bands
    vec2  acc2 = vec2(0.0);
    float wsum = 0.0;           // sum w         -- the two CF denominators,
    float psum = 0.0;           // sum w |s|^2   -- same weights as acc uses
    float psum1 = 0.0;
    float psum2 = 0.0;
    float inv_w = 1.0 / samps;
    float a = max(apod, 1e-4);          // a = 0 would divide by zero below
    for (int i = 0; i < %(N)d; i++) {
        if (alive[i] < 0.5) continue;   // dead element: contributes nothing
        vec2 dv = p - elems[i].xy;
        float d = length(dv);
        int slots = multi_rx != 0 ? 3 : 1;
        for (int slot = 0; slot < slots; ++slot) {
            float row_weight = multi_rx != 0 ? rx_weights[i][slot] : 1.0;
            if (row_weight <= 0.0) continue;
            int rx = neighbor_rx != 0 ? (i ^ 1) : i;
            if (multi_rx != 0) rx += slot == 1 ? -1 : slot == 2 ? 1 : 0;
            vec2 rv = p - elems[rx].xy;
            float rd = length(rv);
            float path = d + rd;
            float t = (path / c + t0_s - dly_s) * fs;
            float cosa = min(dot(dv, elems[i].zw) / max(d, 1e-9),
                             dot(rv, elems[rx].zw) / max(rd, 1e-9));
            if (t >= 0.0 && t <= samps - 1.0 && cosa >= cos_acc) {
                // Index window: v runs 0 at the array centre to 1 at either end,
                // so one ramp handles both ends and stays symmetric under `flip`.
                float v = abs(2.0 * (float(i) / %(Nm1)s) - 1.0);
                float w = apod <= 0.0 ? 1.0 : ramp((1.0 - v) / a);
                // Angular window: u runs 0 at the acceptance edge to 1 on axis.
                // Tapering the outer `a` of the cone is what stops an element from
                // entering the sum at full weight and stepping the image.
                float u = (cosa - cos_acc) / max(1.0 - cos_acc, 1e-6);
                w *= apod <= 0.0 ? 1.0 : ramp(u / a);
                w *= row_weight;
                // A sparse group has exactly one TX from each adjacent pair.
                int row = alternating != 0 ? i / 2 : i * slots + slot;
                vec2 uv = vec2((t + 0.5) * inv_w,
                               (float(row) + 0.5) / float(textureSize(rf0, 0).y));
                vec2 s = texture(rf0, uv).rg;
                acc  += w * s;
                wsum += w;
                psum += w * dot(s, s);      // |s|^2 for the analytic sample
                if (freq_comp > 0.5) {
                    vec2 s1 = texture(rf1, uv).rg;
                    vec2 s2 = texture(rf2, uv).rg;
                    acc1  += w * s1;
                    acc2  += w * s2;
                    psum1 += w * dot(s1, s1);
                    psum2 += w * dot(s2, s2);
                }
            }
        }
    }
    float mag = length(acc);    // envelope of the coherent sum
    if (debug_view == 2) {
        f_mag = clamp(dot(acc, acc) / max(wsum * psum, 1e-20), 0.0, 1.0);
        return;
    }
    if (debug_view == 1) {
        f_mag = mag;
        return;
    }
    if (cf_pow > 0.0) {
        // How much of that sum was actually in phase.  Same weights top and
        // bottom, so a pixel every element agrees on gives 1.0 whatever the
        // taper; Cauchy-Schwarz keeps it inside [0, 1].  wsum == 0 (no element
        // reached this pixel) leaves acc at zero too, so the clamp returns 0.
        float cf = dot(acc, acc) / max(wsum * psum, 1e-20);
        mag *= pow(clamp(cf, 0.0, 1.0), cf_pow);
    }
    if (freq_comp < 0.5) {
        f_mag = mag;                    // preserve the original path exactly
        return;
    }

    // Incoherent frequency compounding: apply coherence independently (it is a
    // per-band phase test), then add DETECTED powers.  The CPU masks are power-
    // complementary, so no /3 brightness correction belongs here.
    float p0 = mag * mag;
    float p1 = dot(acc1, acc1);
    float p2 = dot(acc2, acc2);
    if (cf_pow > 0.0) {
        float cf1 = p1 / max(wsum * psum1, 1e-20);
        float cf2 = p2 / max(wsum * psum2, 1e-20);
        p1 *= pow(clamp(cf1, 0.0, 1.0), 2.0 * cf_pow);
        p2 *= pow(clamp(cf2, 0.0, 1.0), 2.0 * cf_pow);
    }
    f_mag = sqrt(max(p0 + p1 + p2, 0.0));
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
uniform float curve;           // S-curve exponent, 1.0 = linear-in-dB ramp
uniform int debug_view;

// Symmetric S about mid-grey: fold the ramp to u in [-1, 1], raise |u| to a
// power below 1 (which pushes it AWAY from 0), unfold.  Slope is p|u|^(p-1),
// so it is steepest at mid-grey and falls to p at both ends - midtones gain
// contrast, the floor and the highlights give it up.  Fixed points at 0, 0.5
// and 1 mean black stays black and the window edges do not move.
float scurve(float v, float p) {
    if (p >= 0.999) return v;               // identity: skip the pow entirely
    float u = 2.0 * v - 1.0;
    return 0.5 + 0.5 * sign(u) * pow(abs(u), p);
}

void main() {
    float mag  = texture(magtex, v_uv).r;
    if (debug_view == 2) {
        f_color = vec4(vec3(clamp(mag, 0.0, 1.0)), 1.0);
        return;
    }
    float peak = mix(full_scale, max(texelFetch(maxtex, ivec2(0, 0), 0).r, 1e-9),
                     auto_gain);
    float db = 20.0 * log(mag / peak + 1e-9) / log(10.0);
    float v  = clamp((db + gain_db + dyn_db) / dyn_db, 0.0, 1.0);
    v = scurve(v, curve);
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
        self.rf_tex_bands = []      # one normally, FREQ_COMP_BANDS when enabled
        self.tex_samps = 0
        self.tex_rows = 0
        self.tex_bank = None
        self.tex_bands = 0
        self.tex_gen = -1
        self.elem_key = None         # (geom gen, direction) in the 'elems' uniform
        self.dead_key = None         # dead["gen"] in the 'alive' uniform
        self.fb_w = self.fb_h = 1
        self._screen = None
        self._screen_id = -1
        self._q = 0
        self.rendered_generation = -1
        self.rendered_images = 0
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
        self.prog_bf['rf0'].value = 0
        self.prog_bf['rf1'].value = 1
        self.prog_bf['rf2'].value = 2
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
        self.tex_bank = getattr(data, 'bank', None)
        if data.ndim == 3:
            bands = (data,)
        elif data.ndim == 4 and data.shape[0] == FREQ_COMP_BANDS:
            bands = tuple(data)
        else:
            raise ValueError("analytic upload has unexpected shape %r" % (data.shape,))
        nb = len(bands)
        if (self.tex_samps != samps or self.tex_bands != nb or
                self.tex_rows != bands[0].shape[0] or
                not self.rf_tex_bands):
            self._release(self.rf_tex_bands)
            self.rf_tex_bands = []
            for _ in range(nb):
                tex = self.ctx.texture((samps, bands[0].shape[0]), 2, dtype='f4')
                # LINEAR gives fractional-delay interpolation; y is sampled at
                # row centres, so the extra band textures never bleed elements.
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                self.rf_tex_bands.append(tex)
            self.rf_tex = self.rf_tex_bands[0]     # legacy readiness checks
            self.tex_rows = bands[0].shape[0]
            self.tex_samps, self.tex_bands = samps, nb
        for tex, band in zip(self.rf_tex_bands, bands):
            tex.write(band)
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
        dead_key = (dead["gen"], pulser.n_elem, pulser.single_elem, pulser.shot_method, self.tex_bank)
        if self.dead_key != dead_key:
            p['alive'].write(alive_mask(self.tex_bank).tobytes())
            p['rx_weights'].write(multi_rx_weights().tobytes())
            self.dead_key = dead_key
        p['viewbox'].value = (float(vb[0]), float(vb[1]),
                              float(vb[2]), float(vb[3]))
        p['c'].value       = float(state["c"])
        p['dly_s'].value   = float(state["dly_us"]) * 1e-6
        p['fs'].value      = float(FS_HZ)
        p['samps'].value   = float(self.tex_samps)
        p['cos_acc'].value = float(np.cos(np.radians(state["accept"])))
        p['apod'].value    = float(state["apod"])
        p['neighbor_rx'].value = int(pulser.shot_method == 2)
        p['multi_rx'].value = int(self.tex_rows == 3 * N_ELEM)
        p['alternating'].value = int(self.tex_bank is not None)
        p['cf_pow'].value  = float(state["cf"])
        p['debug_view'].value = int(state.get("debug_view", 0))
        p['t0_s'].value    = float(state["t0_ns"]) * 1e-9
        comp = len(self.rf_tex_bands) == FREQ_COMP_BANDS
        p['freq_comp'].value = 1.0 if comp else 0.0
        # Bind rf0 to unused units in the one-band case.  The uniform branch
        # does not sample them, but keeping every sampler complete avoids driver-
        # specific validation surprises.
        for unit in range(FREQ_COMP_BANDS):
            self.rf_tex_bands[min(unit, len(self.rf_tex_bands) - 1)].use(unit)
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
        self.prog_cp['full_scale'].value = full_scale(state["apod"], self.tex_bank)
        self.prog_cp['dyn_db'].value    = float(state["dyn"])
        self.prog_cp['gain_db'].value   = float(state["gain"])
        self.prog_cp['auto_gain'].value = 1.0 if state["auto"] else 0.0
        self.prog_cp['curve'].value     = float(state["curve"])
        self.prog_cp['debug_view'].value = int(state.get("debug_view", 0))
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
        if self.tex_gen != self.rendered_generation:
            self.rendered_generation = self.tex_gen
            self.rendered_images += 1
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
    result = {
        "settings_schema": 1,
        "saved":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "note":    note,
        "host":    os.path.basename(__file__),
        "source":  "file replay" if getattr(main, "debug_offline", False) else ("hardware" if HW else "simulation"),
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
            "tgc_reach_pct": main.tgc_reach_pct,
            "fs_hz":        FS_HZ,
            "n_elem_rx":    N_ELEM,
        },
        "afe": afe_metadata(afe_profile),
        "transmit": {
            "armed":         pulser.arm,
            "shot_method":   pulser.shot_method,
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
            # Which per-element trim calibration was live for this frame.  A
            # snapshot that looks defocused is a different problem depending on
            # whether this was loaded or flat, so record it, not just its rms.
            "trim_note":     pulser.trim_note,
            "trim_ns":       [round(v, 1) for v in pulser.trim_ns],
            "f0_mhz":        round(pulser.f0_hz() / 1e6, 3),
            # f0_mhz above is nominal - for a chirp it is just the mean of the
            # two sliders.  These four are measured off the quantised waveform
            # the FPGA actually fires, and drive_in_band scores them against
            # the probe's passband.  See tx_spectrum().
            "drive_pk_mhz":  round(tx_spectrum()[0], 3),
            "drive_mid_mhz": round(tx_spectrum()[1], 3),
            "drive_lo_mhz":  round(tx_spectrum()[2], 3),
            "drive_hi_mhz":  round(tx_spectrum()[3], 3),
            "drive_in_band": round(tx_in_probe_band(), 3),
            "probe_band_mhz": [PROBE_LO_MHZ, PROBE_HI_MHZ],
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
            "frequency_compounding": state["freq_comp"],
            "frequency_compound_bands": FREQ_COMP_BANDS if state["freq_comp"] and state.get("debug_view", 0) == 0 else 1,
            "frequency_compound_edges_mhz": [
                [round(a / 1e6, 3), round(b / 1e6, 3)]
                for a, b in compound_band_edges()
            ] if state["freq_comp"] and state.get("debug_view", 0) == 0 else [],
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
            "debug_view": state.get("debug_view", 0),
            "dyn_db":     state["dyn"],
            "gain_db":    state["gain"],
            "curve":      state["curve"],
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
            "sweeps_per_s": round(stats['sweep_hz'], 1),
            "complete_sweeps": stats['complete_sweeps'],
            "packet_equivalent_sweeps_per_s": round(stats["fps"] / shots_per_sweep(pulser.shot_method, pulser.n_elem, pulser.single_elem), 1),
            "frames":       stats["frames"],
            "drops":        stats["drops"],
            "resyncs":      stats["resyncs"],
            "holes":        [stats["seq_bad"], stats["seq_chk"]],
            "skips":        stats["skips"],
            "bad_sweeps":   stats["bad_sweeps"],
            "cine_frames":  n_cine,
            "cine_seconds": round(cine_s, 2),
            # where the play head is when frozen: negative = seconds back from
            # live, which is the only thing that says WHICH frame this describes
            "cine_offset_s": (round(main.play_t - main._span(), 3)
                              if state["frozen"] and main.review else None),
        },
    }
    if state["frozen"] and getattr(main, "debug_epoch", None) and not getattr(main, "debug_loading", False):
        # Acquired RF keeps the settings it was collected with during review.
        for section in ("acquisition", "transmit"):
            result[section] = json.loads(json.dumps(main.debug_epoch[section]))
    result["observations"] = {
        "pulser_requested_armed_now": pulser.arm,
        "usb_read_timeouts": stats.get("read_timeouts", 0),
        "timeout_bytes_discarded": stats.get("timeout_bytes_discarded", 0),
        "register_readback": "unavailable; settings describe host requests",
        "loaded_fpga_build": "unknown",
        "last_capability_query": getattr(main, "debug_firmware_info", None),
    }
    result["provenance"] = getattr(main, "debug_source", {})
    result["setup_context"] = getattr(main, "debug_setup", {})
    return result

def write_settings(main, note=""):
    """Write latest.json + a stamped copy, each with the current image beside
    it.  Returns the stamped json path, or None if nothing could be written."""
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1000000000:09d}"
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
            rf_debug.atomic_json(os.path.join(SETTINGS_DIR, name), snap)
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
    def restore(value):
        previous = s.blockSignals(True)
        s.setValue(int(round(value)))
        s.blockSignals(previous)
        vl.setText(f"{value:g}{unit}")
    DEBUG_SLIDERS[label] = (s, restore)
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
    def restore(value):
        previous = s.blockSignals(True)
        s.setValue(int(round(value / step)))
        s.blockSignals(previous)
        last["q"] = quant(value) if quant else None
        vl.setText(f"{fmt % value}{unit}")
    DEBUG_SLIDERS[label] = (s, restore)
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
    so the strip reads directly as how far back in time you are.

    It also carries the IN/OUT marks that bound a video export.  They are part
    of the scrub bar rather than a separate control because the only way to
    choose a clip sensibly is to watch it: park the head on the first frame you
    want, press [, run forward, press ].  Dragging either flag afterwards
    adjusts it against the same time axis the head moves on."""
    scrubbed = Signal(float)            # seconds from the oldest held frame
    marked   = Signal()                 # an in/out mark moved

    GRAB_PX = 7.0                       # flag hit radius

    def __init__(self, parent=None):
        super().__init__(parent)
        self.span = 0.0                 # seconds held
        self.pos  = 0.0                 # play head
        self.live = True                # recording: no head, whole bar filled
        self.t_in  = None               # export marks, seconds into the buffer
        self.t_out = None
        self._drag = None               # None | "scrub" | "in" | "out"
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

    # -- in/out marks ---------------------------------------------------------
    def clear_marks(self):
        self.t_in = self.t_out = None
        self.update()
        self.marked.emit()

    def set_mark(self, which, t):
        """Set one mark and keep the pair ordered.  Pushing IN past OUT (or the
        reverse) moves the other one rather than refusing: the alternative is a
        control that silently ignores the press you just made."""
        t = min(max(float(t), 0.0), self.span)
        if which == "in":
            self.t_in = t
            if self.t_out is not None and self.t_out < t:
                self.t_out = t
        else:
            self.t_out = t
            if self.t_in is not None and self.t_in > t:
                self.t_in = t
        self.update()
        self.marked.emit()

    def selection(self):
        """(t0, t1) of the export range - the whole loop when unmarked."""
        t0 = 0.0 if self.t_in is None else self.t_in
        t1 = self.span if self.t_out is None else self.t_out
        return min(t0, t1), max(t0, t1)

    def _near_mark(self, x):
        best, bd = None, self.GRAB_PX
        for name, t in (("in", self.t_in), ("out", self.t_out)):
            if t is None:
                continue
            d = abs(self._x_at(t) - x)
            if d <= bd:
                best, bd = name, d
        return best

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or self.live or self.span <= 0:
            return
        x = ev.position().x()
        m = self._near_mark(x)
        if m:                           # grabbing a flag must not also seek
            self._drag = m
            self.set_mark(m, self._t_at(x))
        else:
            self._drag = "scrub"
            self.scrubbed.emit(self._t_at(x))

    def mouseMoveEvent(self, ev):
        if self._drag == "scrub":
            self.scrubbed.emit(self._t_at(ev.position().x()))
        elif self._drag in ("in", "out"):
            self.set_mark(self._drag, self._t_at(ev.position().x()))

    def mouseReleaseEvent(self, ev):
        self._drag = None

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

        # export range: everything OUTSIDE it is dimmed, so what is about to be
        # written is what stays lit
        if not self.live and (self.t_in is not None or self.t_out is not None):
            t0, t1 = self.selection()
            x0, x1 = self._x_at(t0), self._x_at(t1)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 0, 0, 120)))
            if x0 > r.left():
                p.drawRect(QRectF(r.left(), r.top(), x0 - r.left(), r.height()))
            if x1 < r.right():
                p.drawRect(QRectF(x1, r.top(), r.right() - x1, r.height()))
            p.setPen(QPen(QColor(MARK_C), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x0, r.top() + 0.5, max(1.0, x1 - x0), r.height() - 1))
            for which, t in (("in", self.t_in), ("out", self.t_out)):
                if t is None:
                    continue
                x = self._x_at(t)
                d = 6.0 if which == "in" else -6.0      # flag points into the clip
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(MARK_C)))
                p.drawRect(QRectF(x - 1.0, r.top() - 4, 2.0, r.height() + 8))
                p.drawPolygon(QPolygonF([QPointF(x, r.top() - 4),
                                         QPointF(x + d, r.top() - 4),
                                         QPointF(x, r.top() + 2)]))

        if not self.live:
            x = self._x_at(self.pos)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#cfe6f5")))
            p.drawRoundedRect(QRectF(x - 2.5, r.top() - 3, 5, r.height() + 6), 2, 2)
        p.end()

#===============================================================================
# cine -> video export
#===============================================================================
# The clip between the IN and OUT marks, re-rendered frame by frame and piped
# raw into ffmpeg.  Nothing is screen-grabbed: every frame goes back through
# the beamformer at the export resolution (exactly what CAPTURE does for a
# still), so a 4K export is genuinely reconstructed at 4K rather than an
# upscale of a ~900 px window, and the axes, calipers and M-line are painted at
# the matching scale on top.
#
# Frames are resampled onto a fixed output rate rather than written one-per-
# recorded-sweep.  The recorder runs at whatever the FPGA delivers (~130/s,
# jittery), which is not a legal video frame rate and would play back at the
# wrong speed anywhere; picking the frame that was live at each output instant
# keeps replay honest and makes the speed multiplier exact.
#
# Encoding targets what YouTube actually ingests: H.264 High in yuv420p at
# bt709, closed 2 s GOP, faststart, CRF rather than a bitrate cap.  CRF 18 at
# 4K lands well inside YouTube's ~45 Mbit/s recommendation while staying at the
# "cannot see the difference" end - which matters here because ultrasound
# speckle is high-entropy noise-like detail and is the first thing a codec
# throws away.  Speckle is also why the files are not small for the duration:
# there is no static background to predict.
VID_FOOT = 34                       # footer band under the axes (at scale 1)

VID_RES = [("4K UHD - 3840 x 2160", 3840, 2160),
           ("1440p - 2560 x 1440",  2560, 1440),
           ("1080p - 1920 x 1080",  1920, 1080)]

VID_FPS = [24, 25, 30, 50, 60]

#      label                                     crf  x264/x265 preset
VID_Q = [("archive - near lossless, big file",    14, "slow"),
         ("high - recommended for YouTube",       18, "medium"),
         ("compact - smallest, still clean",      22, "medium")]

def find_ffmpeg():
    """PATH, then $FFMPEG, then the imageio wheel a lot of python installs
    already carry.  Returns None if there is nothing to pipe into."""
    exe = os.environ.get("FFMPEG")
    if exe and os.path.isfile(exe):
        return exe
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def ffmpeg_cmd(exe, w, h, fps, crf, preset, hevc, path):
    v = (["-c:v", "libx265", "-preset", preset, "-crf", str(crf + 2),
          "-tag:v", "hvc1", "-pix_fmt", "yuv420p"] if hevc else
         ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
          "-profile:v", "high", "-pix_fmt", "yuv420p", "-sc_threshold", "0"])
    return [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
            "-an", *v,
            "-g", str(int(fps * 2)), "-keyint_min", str(int(fps)),
            "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-movflags", "+faststart", path]

def qimage_rgb888(img):
    """Tightly packed RGB bytes.  QImage pads every row out to a 4-byte
    boundary, and ffmpeg's rawvideo demuxer does not expect that padding, so
    the stride has to be cut off rather than assumed away."""
    if img.format() != QImage.Format_RGB888:
        img = img.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    a = np.frombuffer(memoryview(img.constBits()), np.uint8,
                      count=bpl * h).reshape(h, bpl)
    return np.ascontiguousarray(a[:, :3 * w]).tobytes()

def video_scale(fb_w, fb_h, out_w, out_h):
    """Render scale that makes the composed frame as large as fits inside the
    output canvas, keeping the on-screen aspect (no stretching, no cropping -
    a 16:9 canvas around a 4:3 image gets pillarboxed)."""
    bw, bh = fb_w + ML + MR, fb_h + MT + MB + VID_FOOT
    return max(0.25, min(out_w / float(bw), out_h / float(bh)))

def render_video_frame(img, vb, measures, mline_ab, foot, s, out_w, out_h,
                       canvas=None):
    """One composed video frame: B-mode + axes + calipers + M-line + footer,
    centred in an exactly (out_w, out_h) canvas.  Every frame in a clip has to
    be byte-identical in size, hence the fixed canvas and the padding."""
    if canvas is None:
        canvas = QImage(out_w, out_h, QImage.Format_RGB888)
    canvas.fill(QColor(PLOT_BG))
    iw, ih = img.width(), img.height()
    ml, mt, mr, mb = int(ML*s), int(MT*s), int(MR*s), int(MB*s)
    ft = int(VID_FOOT * s)
    cw, ch = iw + ml + mr, ih + mt + mb + ft
    p = QPainter(canvas)
    p.translate(int((out_w - cw) / 2), int((out_h - ch) / 2))
    r = QRectF(ml, mt, iw, ih)
    p.drawImage(QPointF(ml, mt), img)
    paint_axes(p, r, vb, s)
    paint_measures(p, r, vb, measures, s)
    if mline_ab is not None:
        paint_mline(p, r, vb, mline_ab[0], mline_ab[1], None, s)
    if foot:
        # shrink to fit rather than clip: the info line is long, and the one
        # thing worse than small text is a truncated acquisition setting
        fs = max(6, int(8 * s))
        while fs > 6:
            fm = QFontMetrics(QFont("Consolas", fs))
            if max(fm.horizontalAdvance(t) for t in foot) <= iw:
                break
            fs -= 1
        f = QFont("Consolas", fs)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(QPen(QColor(DIM)))
        y = mt + ih + mb + (ft - len(foot) * fm.height()) / 2 + fm.ascent()
        for t in foot:
            p.drawText(QPointF(ml, y), t)
            y += fm.height()
    p.end()
    return canvas

class VideoExportDialog(QDialog):
    """Output options.  The range itself comes from the timeline marks, so this
    only has to answer 'how is it written', not 'what is written'."""
    def __init__(self, span_s, n_frames, speed, fb_w, fb_h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("export cine as video")
        self.setStyleSheet(APP_QSS)
        g = QGridLayout(self); g.setContentsMargins(10, 10, 10, 10); g.setSpacing(6)

        def row(i, text, w, tip=""):
            lb = QLabel(text); lb.setStyleSheet(f"color:{DIM};")
            if tip:
                lb.setToolTip(tip); w.setToolTip(tip)
            g.addWidget(lb, i, 0); g.addWidget(w, i, 1)
            return w

        self.res = QComboBox()
        for lab, _, _ in VID_RES:
            self.res.addItem(lab)
        row(0, "resolution", self.res,
            "the clip is RE-BEAMFORMED at this size, not upscaled from the\n"
            "window - 4K costs render time per frame but is real detail")

        self.fps = QComboBox()
        for f in VID_FPS:
            self.fps.addItem(f"{f} fps")
        self.fps.setCurrentIndex(VID_FPS.index(30))
        row(1, "frame rate", self.fps,
            "output rate.  The recorder runs faster than this (~130 sweeps/s),\n"
            "so at 1x the nearest recorded frame to each output instant is used")

        self.spd = QDoubleSpinBox()
        self.spd.setRange(SPEED_MIN, SPEED_MAX); self.spd.setSingleStep(0.05)
        self.spd.setDecimals(2); self.spd.setValue(float(speed))
        self.spd.setSuffix("x")
        row(2, "speed", self.spd,
            "1x is real time.  Below 1x the clip is slowed down - no frames are\n"
            "invented, each recorded frame is simply held for longer")

        self.q = QComboBox()
        for lab, _, _ in VID_Q:
            self.q.addItem(lab)
        self.q.setCurrentIndex(1)
        row(3, "quality", self.q,
            "constant-quality encode (CRF).  Ultrasound speckle is noise-like\n"
            "detail and is the first thing a codec discards, so 'high' is\n"
            "already conservative; 'archive' is for keeping, not uploading")

        self.hevc = QCheckBox("H.265 / HEVC (smaller, slower to encode)")
        self.hevc.setToolTip("YouTube accepts both.  H.264 is the safe default and\n"
                             "plays everywhere; H.265 is roughly 30% smaller.")
        g.addWidget(self.hevc, 4, 1)

        self.overlay = QCheckBox("burn in axes, calipers, M-line and settings")
        self.overlay.setChecked(True)
        self.overlay.setToolTip("off writes the bare B-mode image only")
        g.addWidget(self.overlay, 5, 1)

        self.info = QLabel(""); self.info.setStyleSheet(f"color:{DIM};")
        g.addWidget(self.info, 6, 0, 1, 2)
        self._span, self._nf = span_s, n_frames
        self._fb = (fb_w, fb_h)
        for w in (self.res, self.fps, self.q):
            w.currentIndexChanged.connect(self._refresh)
        self.spd.valueChanged.connect(self._refresh)
        self.hevc.toggled.connect(self._refresh)
        self._refresh()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("export…")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        g.addWidget(bb, 7, 0, 1, 2)

    def _refresh(self):
        o = self.opts()
        n = max(1, int(round(self._span / max(o["speed"], 1e-6) * o["fps"])))
        # crude size guide from the CRF/resolution pair - enough to tell a
        # 200 MB upload from a 2 GB one before spending ten minutes on it
        mbps = {14: 90.0, 18: 38.0, 22: 16.0}[o["crf"]] * \
               (o["w"] * o["h"]) / (3840.0 * 2160.0) * (0.7 if o["hevc"] else 1.0)
        secs = n / float(o["fps"])
        # What actually gets rendered inside the canvas.  The frame keeps the
        # window's aspect, so a tall window is pillarboxed into 16:9 - worth
        # saying out loud, because the fix is to widen the window before
        # freezing, not anything in this dialog.
        fw, fh = self._fb
        s  = video_scale(fw, fh, o["w"], o["h"])
        cw = int(fw*s) + int(ML*s) + int(MR*s)
        ch = int(fh*s) + int(MT*s) + int(MB*s) + int(VID_FOOT*s)
        bars = ("" if (o["w"] - cw) <= 8 and (o["h"] - ch) <= 8 else
                f"  (image {cw}x{ch} centred in it - resize the window towards "
                f"16:9 to fill the frame)")
        self.info.setText(f"{self._nf} recorded frames → {n} video frames · "
                          f"{secs:.1f} s at {o['fps']} fps · roughly "
                          f"{mbps * secs / 8:.0f} MB\n{o['w']}x{o['h']}{bars}")

    def opts(self):
        lab, w, h = VID_RES[self.res.currentIndex()]
        _, crf, preset = VID_Q[self.q.currentIndex()]
        return {"w": w, "h": h, "fps": VID_FPS[self.fps.currentIndex()],
                "speed": float(self.spd.value()), "crf": crf, "preset": preset,
                "hevc": self.hevc.isChecked(),
                "overlay": self.overlay.isChecked()}

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
AUDIO_F_LO  = 150.0         # band centre at the FAR end of the line
AUDIO_F_HI  = 900.0         # band centre at the NEAR end
AUDIO_GATE  = 0.04          # motion below this fraction of peak is silence
AUDIO_SENS  = 6.0           # motion -> loudness

# The voice is a BAND, not a tone.  Real Doppler audio is broadband - a whole
# distribution of velocities scattering at once - and it is that spread which
# makes it a whoosh rather than a whistle.  We have no velocity spectrum to put
# there (see the class docstring), so the band is synthesised: partials spread
# log-symmetrically around the centre frequency, each with its own slowly
# random-walking amplitude.  Their mutual beating is the rustle; the walk is
# what stops it settling into a chord.
AUDIO_NPART = 28            # partials across the band
AUDIO_BW    = 1.05          # half-width in octaves (band spans ~2*BW octaves)
AUDIO_WALK  = 0.22          # how far the partial amplitudes move per block
AUDIO_ATK   = 0.55          # envelope follow, rising  (fast: crisp whoosh onset)
AUDIO_REL   = 0.10          # envelope follow, falling (slow: it swells away)

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
        self.amp, self.freq = 0.0, AUDIO_F_LO
        self.gain = 0.5
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self._fill)

        # Partial layout, fixed for the life of the synth.  Ratios are log-spaced
        # about the centre so the band keeps its shape as the centre slides with
        # position; the Gaussian weight softens both edges so nothing pings out
        # as a discrete tone, and the slight downward skew of the top end leaves
        # more of the energy below centre, which is the half that sounds like
        # tissue rather than like hiss.
        self.rng   = np.random.default_rng(0xB100D)
        self.ratio = 2.0 ** np.linspace(-AUDIO_BW, AUDIO_BW * 0.75, AUDIO_NPART)
        w = np.exp(-0.5 * (np.log2(self.ratio) / (AUDIO_BW * 0.6)) ** 2)
        self.wgt  = w / np.sqrt((w * w).sum())   # unit RMS whatever NPART is
        self.pph  = self.rng.uniform(0.0, 2.0 * np.pi, AUDIO_NPART)
        self.pamp = self.wgt.copy()

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
        self.amp  = 0.0
        self.pamp = self.wgt.copy()
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
        # train of them is worse than the sound itself.  The envelope follows
        # asymmetrically, fast up and slow down, so a pulsation arrives as one
        # whoosh that swells and decays rather than as a burst of chatter that
        # tracks every wobble in the motion energy.
        k  = AUDIO_ATK if a > self.amp else AUDIO_REL
        a1 = self.amp  + (a - self.amp) * k
        f1 = self.freq + (f - self.freq) * 0.25
        av = np.linspace(self.amp,  a1, n)
        fv = np.linspace(self.freq, f1, n)

        # One phase ramp for the centre; each partial rides it scaled by its own
        # ratio, and carries its own phase across the block boundary, so the
        # whole band stays continuous through a frequency slide with a single
        # cumsum rather than one per partial.
        cs  = np.cumsum(fv) * (2.0 * np.pi / AUDIO_SR)          # (n,)
        ph  = self.pph[None, :] + cs[:, None] * self.ratio[None, :]
        self.pph = np.mod(self.pph + cs[-1] * self.ratio, 2.0 * np.pi)

        # New random target for every partial each block, approached gradually:
        # the band shimmers instead of stepping, and no partial holds a level
        # long enough to be heard as a note of its own.
        pa1  = self.pamp + (self.wgt * self.rng.uniform(0.3, 1.7, AUDIO_NPART)
                            - self.pamp) * AUDIO_WALK
        ramp = np.linspace(0.0, 1.0, n)[:, None]
        pa   = self.pamp[None, :] + (pa1 - self.pamp)[None, :] * ramp
        self.pamp = pa1
        self.amp, self.freq = float(a1), float(f1)

        # tanh rather than a hard clip: a noise band has a much worse crest
        # factor than a sine, so the loud peaks WILL hit the rail, and doing it
        # softly rounds them off into the whoosh instead of crackling.
        mix = (np.sin(ph) * pa).sum(axis=1)
        w   = np.tanh(mix * av * self.gain * 1.7) * 30000.0
        self.dev.write(w.astype(np.int16).tobytes())

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
        v   = scurve_np(v)
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
class Main(DebugMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TFM B-mode - {N_ELEM} element convex, GPU beamformer"
                            + ("" if HW else "  [SIMULATION]"))
        self.captures = []
        self.dialogs = []
        self.last = None
        self.tgc_lo, self.tgc_hi = TGC_MIN_DEF, TGC_MAX_DEF
        self.tgc_reach_pct = TGC_REACH_DEF
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
        tgc_knee = mkslider(r2, "TGC full @", 1, 100, TGC_REACH_DEF,
                            on_change=self.set_tgc_reach, width=98, unit="%")
        tgc_knee.setToolTip("Depth fraction where the TGC ramp reaches its maximum; "
                            "the FPGA holds that gain for the rest of the receive window.")
        # A wider log window can retain faint gray while lowering display gain
        # enough to keep a strong reflector from becoming a solid white band.
        mkslider(r2, "dyn range", 20, 100, DYN_DEF, on_change=self.set_dyn,
                 width=96, unit="dB")
        mkslider(r2, "gain", -40, 40, GAIN_DEF, on_change=self.set_gain,
                 width=96, unit="dB")
        # Integer percent so it rides the same slider plumbing as coh/apod;
        # set_curve divides it back down.  100% is the identity.
        mkslider(r2, "curve", int(round(CURVE_MIN * 100)), 100,
                 int(round(CURVE_DEF * 100)), on_change=self.set_curve,
                 width=96, unit="%")
        self.cb_auto = QCheckBox("auto gain")
        self.cb_auto.setChecked(state["auto"])
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
        rdebug = QHBoxLayout(); rdebug.setSpacing(4); root.addLayout(rdebug)
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
        self.t_draw.setTimerType(Qt.TimerType.PreciseTimer)
        self.t_draw.start(16)
        self.t_stat = QTimer(self); self.t_stat.timeout.connect(self._status)
        self.render_clock = time.perf_counter()
        self.render_count = 0
        self.t_stat.start(250)
        self.t_play = QTimer(self); self.t_play.timeout.connect(self._play_tick)
        self.t_play.setTimerType(Qt.TimerType.PreciseTimer)

        for key, fn in ((Qt.Key_Space,  self._space),
                        (Qt.Key_Escape, lambda: self.b_freeze.setChecked(False)),
                        (Qt.Key_Comma,  lambda: self.step(-1)),
                        (Qt.Key_Period, lambda: self.step(+1)),
                        (Qt.Key_I,      lambda: self.mark("in")),
                        (Qt.Key_O,      lambda: self.mark("out"))):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

        self._cine_enable(False)
        self.pls_refresh()          # fills the f0/frame-rate readout at startup
        self.debug_init(globals(), rdebug)
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

        self.cb_freq = QCheckBox("freq compound")
        self.cb_freq.setChecked(FREQ_COMP_DEF)
        self.cb_freq.setToolTip(
            "split the selected receive passband into %d sub-bands, beamform "
            "each independently, then add their detected powers.\n\nAnatomy "
            "stays registered while wavelength-dependent speckle changes, so "
            "the image becomes less grainy. This is INCOHERENT compounding - "
            "unlike the RF avg control, which removes electronic noise but "
            "does not remove stationary speckle.\n\nThe masks are power-"
            "complementary, so brightness is preserved. The cost is %dx the "
            "inverse FFT and beamformer work, plus lower axial resolution in "
            "each narrower band. At the 5 MHz default, each band is about "
            "1.7 MHz wide (roughly 0.45 mm c/2B).\n\nRequires bandpass; "
            "turning this on enables it automatically. Compare with coherence "
            "near zero first, because coherence also changes speckle."
            % (FREQ_COMP_BANDS, FREQ_COMP_BANDS))
        self.cb_freq.toggled.connect(self.set_freq_comp)
        row.addWidget(self.cb_freq)

        self.cb_mf = QCheckBox("pulse comp")
        self.cb_mf.setChecked(MF_ON_DEF)
        self.cb_mf.setToolTip(
            "Pulse compression: correlate signed RF with the commanded transmit "
            "reference before envelope detection.\n\nThis is separate from the "
            "chirp checkbox. A longer chirp with compression OFF stretches each "
            "echo in depth. With compression ON, the usable bandwidth limits "
            "how short the echo can become.\n\nLive settings rebuild the reference; "
            "RF replay uses the reference saved in the recording. No new "
            "transmission is needed to compare compression on/off in replay.\n\n"
            "The reference does not include measured probe or analog-path response. "
            "Mismatch can leave axial ringing/sidelobes. Band limiting can reduce "
            "ringing but also broadens the compressed echo. Verify width and range "
            "on an isolated reflector; brightness alone is not an SNR measurement.")
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
            "error from the coherent sum.\n\nCurrent RTL locks transmit launch to an "
            "ADC-grid marker and no longer lets\nthe USB/header FIFO move the "
            "range gate. This measures the small residual\n(two-flop clock "
            "crossing, analog path, or marginal LVDS capture) rather than\n"
            "trying to repair a torn sweep; torn sweeps are rejected at ingest."
            "\n\nNEEDS A BACKGROUND "
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
        if not v and self.cb_freq.isChecked():
            self.cb_freq.setChecked(False)
        state["band_on"] = bool(v)
        self._refresh_rx()

    def set_freq_comp(self, v):
        if v and not self.cb_band.isChecked():
            self.cb_band.setChecked(True)
        state["freq_comp"] = bool(v)
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
        pls("dead ns", T_DEAD_MIN_NS, 200, 10, pulser.t_dead_ns, pulser.set_t_dead_ns,
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
        send_pls_rx covers nominal capture time. The capture-ready FPGA
        interlock additionally holds the next shot when USB backpressure extends
        the actual drain; older bitstreams lack that feedback.
        """
        if pulser.shot_method == 1:
            tx = "Golay A/B, 4 chips per shot, %.2f MHz" % (pulser.f0_hz()/1e6)
        elif pulser.chirp_on:
            tx = ("chirp %.1f-%.1f MHz  burst %.1f us"
                  % (pulser.chirp_f0_mhz, pulser.chirp_f1_mhz,
                     pulser.burst_ns() / 1e3))
        else:
            tx = ("f0 %.2f MHz  burst %.0f ns"
                  % (pulser.f0_hz() / 1e6, pulser.burst_ns()))
        # The sliders above are the REQUEST; this is the quantised waveform the
        # FPGA will really fire, measured.  See tx_spectrum().
        pk, mid, lo, hi = tx_spectrum()
        tx += ("   -> drive %.2f-%.2f MHz  pk %.2f  mid %.2f  %.0f%% in %.0f-%.0f"
               % (lo, hi, pk, mid, 100.0 * tx_in_probe_band(),
                  PROBE_LO_MHZ, PROBE_HI_MHZ))
        self.pls_lbl.setText(
            "%s  elem %.0f us  nominal frame %.1f ms (up to %.1f fps)%s"
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

        # -- export range ------------------------------------------------------
        self.b_in  = QPushButton("[")
        self.b_out = QPushButton("]")
        self.b_clr = QPushButton("×")
        for b, tip in ((self.b_in,  "mark clip START at the play head  (i)\n"
                                    "the flags can also be dragged on the bar"),
                       (self.b_out, "mark clip END at the play head  (o)"),
                       (self.b_clr, "clear the marks - export the whole loop")):
            b.setFixedWidth(24)
            b.setToolTip(tip)
            h.addWidget(b)
        self.b_in.clicked.connect(lambda: self.mark("in"))
        self.b_out.clicked.connect(lambda: self.mark("out"))
        self.b_clr.clicked.connect(self.clear_marks)

        self.tl = Timeline()
        self.tl.scrubbed.connect(self.scrub)
        self.tl.marked.connect(self._cine_text)
        h.addWidget(self.tl, 1)

        self.cine_lbl = QLabel("")
        self.cine_lbl.setStyleSheet(f"color:{DIM};")
        self.cine_lbl.setFixedWidth(178)
        self.cine_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.cine_lbl)

        self.b_exp = QPushButton("export video…")
        self.b_exp.setToolTip(
            "write the marked range (or the whole loop) as a video file.\n\n"
            "Every frame is re-beamformed at the export resolution, so a 4K\n"
            "export is reconstructed at 4K rather than upscaled - and the axes,\n"
            "calipers, M-line and the settings footer are drawn to match.\n\n"
            "Needs ffmpeg on PATH (or $FFMPEG).")
        self.b_exp.clicked.connect(self.export_video)
        h.addWidget(self.b_exp)

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
        if on and not getattr(self, "method_verified", True):
            self.cb_arm.setChecked(False)
            return
        pulser.set_arm(bool(on)); self.pls_refresh()
        if hasattr(self, "g"):
            self.debug_lock_acquisition(state["frozen"])

    def set_single(self, on):
        pulser.set_single_elem(self.elem_v if on else None)
        self.pls_refresh()

    def set_chirp(self, on):
        pulser.set_chirp_on(bool(on))
        self.pls_refresh()
    def set_dyn(self, v):     state["dyn"] = float(v);    self.scene.gl.update()
    def set_gain(self, v):    state["gain"] = float(v);   self.scene.gl.update()
    def set_curve(self, v):   state["curve"] = v / 100.0; self.scene.gl.update()

    def _send_tgc(self):
        lo, hi = self.tgc_lo, max(self.tgc_lo, self.tgc_hi)
        inc = tgc_increment(lo, hi, cfg["win_words"], self.tgc_reach_pct)
        send_cmd(cmd(OP_SEQ_TGC0, lo), "seq_tgc0")
        send_cmd(cmd(OP_SEQ_TGC1, hi), "seq_tgc1")
        send_cmd(cmd(OP_SEQ_TGC, inc), "seq_tgc")

    def set_tgc_lo(self, v): self.tgc_lo = v; self._send_tgc()
    def set_tgc_hi(self, v): self.tgc_hi = v; self._send_tgc()
    def set_tgc_reach(self, v): self.tgc_reach_pct = float(v); self._send_tgc()

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
        self.b_bg.setText(f"capturing {bg['want']}")

    def clear_bg(self):
        bg.update(ref=None, acc=None, n=0, want=0)
        self.cb_bg.setChecked(False)
        self.b_bg.setText("capture bg")

    def set_frozen(self, v):
        """FREEZE is also the entry point to the cine loop: it stops the
        recorder and takes a stable snapshot of everything still in it, so the
        frames cannot shift under the timeline while it is being scrubbed."""
        if not v and (getattr(self, "debug_jobs", []) or getattr(self, "debug_offline", False)):
            previous = self.b_freeze.blockSignals(True)
            self.b_freeze.setChecked(True)
            self.b_freeze.blockSignals(previous)
            return
        if v and hasattr(self, "g"):
            self.debug_tick()
        state["frozen"] = v
        self.b_freeze.setText("FROZEN - click to resume" if v else "FREEZE")
        self.tl.t_in = self.tl.t_out = None      # marks belong to one snapshot
        if v:
            self.review, self.rev_t = cine.freeze()
            self.debug_after_freeze()
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
            self.debug_after_freeze()

    # -- cine transport -------------------------------------------------------
    def _cine_enable(self, on):
        for w in (self.b_play, self.b_stepb, self.b_stepf, self.b_rep,
                  self.b_in, self.b_out, self.b_clr, self.b_exp):
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
        if pulser.shot_method == ALTERNATING_24:
            return BankFrame(self.review[i][1], self.debug_review_quality[i]["bank"])
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
        txt = (f"{self.play_t - self._span():+6.2f} s   "
               f"{self.cur_idx + 1}/{len(self.review)}")
        if self.tl.t_in is not None or self.tl.t_out is not None:
            i0, i1 = self._sel_idx()
            t0, t1 = self.tl.selection()
            txt += f"\nclip {t1 - t0:.2f} s · {i1 - i0 + 1} f"
        self.cine_lbl.setText(txt)

    # -- export range ---------------------------------------------------------
    def mark(self, which):
        """Put a clip mark at the play head."""
        if not self.review or not state["frozen"]:
            return
        self.tl.set_mark(which, self.play_t)

    def clear_marks(self):
        self.tl.clear_marks()

    def _sel_idx(self):
        """Recorded-frame index range covered by the marks, inclusive."""
        t0, t1 = self.tl.selection()
        i0 = int(np.searchsorted(self.rev_t, t0, side="right")) - 1
        i1 = int(np.searchsorted(self.rev_t, t1, side="right")) - 1
        n  = len(self.review)
        return min(max(i0, 0), n - 1), min(max(i1, 0), n - 1)

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
            self.t_play.start(8 if pulser.shot_method == ALTERNATING_24 else 10)

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

    # -- video export ---------------------------------------------------------
    def export_video(self):
        if not state["frozen"] or not self.review:
            return
        self._stop_play()
        exe = find_ffmpeg()
        if exe is None:
            QMessageBox.warning(
                self, "ffmpeg not found",
                "Video export pipes frames into ffmpeg, and there is no ffmpeg "
                "on PATH.\n\nInstall it (winget install Gyan.FFmpeg, or "
                "ffmpeg.org/download), or point the FFMPEG environment variable "
                "at the executable, and try again.\n\nCAPTURE still writes "
                "single frames as PNG without it.")
            return
        t0, t1 = self.tl.selection()
        i0, i1 = self._sel_idx()
        if t1 - t0 < 1e-3 or i1 <= i0:
            QMessageBox.information(
                self, "empty clip",
                "The marked range holds one frame or less.\n\nScrub to the "
                "first frame you want and press [ , then to the last and press "
                "] - or clear the marks with × to export the whole loop.")
            return
        dlg = VideoExportDialog(t1 - t0, i1 - i0 + 1, self.speed,
                                self.scene.gl.fb_w, self.scene.gl.fb_h, self)
        if dlg.exec() != QDialog.Accepted:
            return
        o = dlg.opts()
        home = os.path.expanduser("~")
        vids = os.path.join(home, "Videos")
        path, _ = QFileDialog.getSaveFileName(
            self, "export cine video",
            os.path.join(vids if os.path.isdir(vids) else home,
                         f"cine_{time.strftime('%Y%m%d_%H%M%S')}.mp4"),
            "MP4 video (*.mp4)")
        if not path:
            return
        if not path.lower().endswith(".mp4"):
            path += ".mp4"
        keep_t = self.play_t
        try:
            self._write_video(exe, path, i0, i1, t0, t1, o)
        finally:
            # put the transport back where it was: the export walked play_t and
            # the GL texture across the whole clip
            self.play_t, self.cur_idx = keep_t, -1
            self._seek(keep_t, force=True)

    def _write_video(self, exe, path, i0, i1, t0, t1, o):
        gl   = self.scene.gl
        w, h, fps = o["w"], o["h"], o["fps"]
        s    = video_scale(gl.fb_w, gl.fb_h, w, h)
        n    = max(1, int(round((t1 - t0) / max(o["speed"], 1e-6) * fps)))
        meas = [list(m) for m in self.scene.ov.measures] if o["overlay"] else []
        mab  = (mline["a"], mline["b"]) if (o["overlay"] and mline["on"]) else None
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")

        prog = QProgressDialog("preparing…", "cancel", 0, n, self)
        prog.setWindowTitle("export video")
        prog.setStyleSheet(APP_QSS)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False); prog.setAutoReset(False)
        prog.setValue(0)
        QApplication.processEvents()

        log = tempfile.TemporaryFile()
        # CREATE_NO_WINDOW: ffmpeg is a console program and would otherwise
        # flash a window over the UI for the length of the encode
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                ffmpeg_cmd(exe, w, h, fps, o["crf"], o["preset"], o["hevc"], path),
                stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=flags)
        except OSError as e:
            prog.close()
            QMessageBox.critical(self, "export failed", f"could not run ffmpeg:\n{e}")
            return

        canvas = QImage(w, h, QImage.Format_RGB888)
        last_i, payload, wrote = -1, None, 0
        cancelled, broke = False, False
        t_start = time.perf_counter()
        try:
            for k in range(n):
                if prog.wasCanceled():
                    cancelled = True
                    break
                tt = t0 + (k / float(fps)) * o["speed"]
                i  = int(np.searchsorted(self.rev_t, min(tt, t1), side="right")) - 1
                i  = min(max(i, i0), i1)
                # At 60 fps out and ~130 sweeps/s in, or at any speed below 1x,
                # the same recorded frame lands on several output frames.  It is
                # the same picture, so render it once and re-send the bytes -
                # which is most of the export time at slow speeds.
                if i != last_i or payload is None:
                    payload = self._export_frame(i, tt, s, o, meas, mab, canvas,
                                                 stamp, w, h)
                    last_i = i
                if payload is None:
                    broke = True
                    break
                proc.stdin.write(payload)
                wrote += 1
                if k % 4 == 0 or k == n - 1:
                    el  = time.perf_counter() - t_start
                    eta = el / max(k + 1, 1) * (n - k - 1)
                    prog.setLabelText(f"frame {k+1} / {n}   ({el:.0f} s elapsed, "
                                      f"~{eta:.0f} s left)")
                    prog.setValue(k + 1)
                    self.tl.pos = tt
                    self.tl.update()
                    QApplication.processEvents()
        except (BrokenPipeError, OSError):
            broke = True                # ffmpeg died: the log below says why
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            rc = proc.wait()
            prog.close()

        log.seek(0)
        msg = log.read().decode("utf-8", "replace").strip()
        log.close()

        if cancelled:
            try:
                os.remove(path)
            except OSError:
                pass
            self.set_lbl.setText("video export cancelled")
            self.set_lbl.setStyleSheet(f"color:{WARN_C};")
            return
        if rc != 0 or broke or wrote == 0:
            print(f"[ffmpeg rc={rc}]\n{msg}")
            QMessageBox.critical(self, "export failed",
                                 (msg or f"ffmpeg exited with code {rc}")[:2000])
            return
        mb  = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0.0
        dur = wrote / float(fps)
        print(f"wrote {path}  ({wrote} frames, {dur:.1f} s, {w}x{h}, {mb:.1f} MB)")
        # the status bar is rewritten by the 250 ms stats tick, so the result
        # goes where it will still be readable in a minute
        self.set_lbl.setText(f"video {os.path.basename(path)} · {dur:.1f} s · "
                             f"{mb:.1f} MB")
        self.set_lbl.setStyleSheet(f"color:{OK_C};")
        self.set_lbl.setToolTip(path)

    def _export_frame(self, i, tt, s, o, meas, mab, canvas, stamp, w, h):
        """Recorded frame i, re-beamformed at export scale and composed.
        Returns packed RGB bytes, or None if the GL side had nothing to give."""
        publish_replay_sync(self._review_rf(i))
        gl = self.scene.gl
        # A real repaint, not update(): it forces the upload of the frame just
        # published and refreshes the max-reduce chain, which is where the
        # auto-gain reference comes from.  It also means the window shows the
        # export running rather than one frozen frame.
        gl.repaint()
        img, vb = gl.grab_bmode(s)
        if img is None:
            return None
        foot = []
        if o["overlay"]:
            self.play_t, self.cur_idx = tt, i
            foot = [f"{stamp}   frame {i+1}/{len(self.review)}   "
                    f"{o['fps']} fps · {o['speed']:.2f}x replay",
                    self.info_line()]
        render_video_frame(img, vb, meas, mab, foot, s, w, h, canvas)
        return qimage_rgb888(canvas)

    def _space(self):
        if state["frozen"]:
            self.toggle_play()
        else:
            self.b_freeze.setChecked(True)

    def apply_depth(self, v):
        """Depth changes the frame size: stop, drain, swap buffers, reconfigure."""
        global raw_buf, live_buf, carry, _prev_elem, _sweep_ok, _rej_run
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
            golay_pairs.pending = None
            three_rx_groups.reset()
            raw_buf = np.zeros((N_ELEM, cfg["samps"] * windows_per_tx(pulser.shot_method)), dtype=np.int16)
            live_buf = np.zeros_like(raw_buf)
            carry = np.empty(0, dtype=np.uint32)
            stats["last_fcnt"] = None
            _prev_elem = -1
            _sweep_seen.fill(False)
            _sweep_ok = True
            _rej_run = 0
        send_seq_config(self.tgc_lo, max(self.tgc_lo, self.tgc_hi),
                        int(state["dly_us"]), self.gap, self.tgc_reach_pct)
        send_cmd(cmd(OP_START), "start")
        view["cz"] = None                     # depth changed: recentre vertically
        self.pls_refresh()      # send_seq_config resized t_rx with the window

    # -- capture --------------------------------------------------------------
    def info_line(self):
        paths = {3: "three-position RX  ", ALTERNATING_24: "24 shots/image  "}.get(pulser.shot_method, "")
        return (f"{N_ELEM} el  {paths}depth {state['depth_cm']} cm  c {state['c']:.0f} m/s  "
                f"dly {state['dly_us']:.0f} us  aper {state['accept']:.0f} deg  "
                f"apod {state['apod']*100:.0f}%  "
                # Only when on: CF makes brightness non-quantitative, so a
                # capture has to carry the fact that it was applied.
                + (f"coh {state['cf']:.2f}  " if state["cf"] > 0 and state.get("debug_view", 0) == 0 else "")
                + ({1: "ordinary DAS  ", 2: "CF map 0-1  "}.get(state.get("debug_view", 0), ""))
                # The measured -6 dB drive span, not the chirp sliders.  Two
                # captures at different transmit frequencies are not comparable
                # at all, and until now the caption recorded the RECEIVE band
                # while saying nothing about what was transmitted into it.
                + ("drive %.1f-%.1f MHz  " % tx_spectrum()[2:])
                + (f"burst {pulser.burst_ns()/1000:.2f} us  "
                   f"pulse-comp {'on' if state['mf'] else 'off'}  ")
                # Both of these change the noise floor the image sits on, so a
                # capture is not comparable to another one without them.
                + ("band %.1f-%.1f MHz  " % tuple(f / 1e6 for f in band_edges())
                   if state["band_on"] else "")
                + (f"freq-comp x{FREQ_COMP_BANDS}  " if state["freq_comp"] and state.get("debug_view", 0) == 0 else "")
                + (f"avg {rf_avg.n} sw  " if rf_avg.n > 1 else "")
                + (f"de-jit {jit['rms_ns']:.1f} ns rms  " if state["jit"] else "")
                + f"t0 {state['t0_ns']:+.0f} ns  "
                f"R {geom['R_mm']:.1f} mm  pitch {geom['pitch_mm']:.4f} mm  "
                f"dyn {state['dyn']:.0f} dB  gain {state['gain']:+.0f} dB  "
                # only when it is doing something: 1.00 is the identity, and a
                # burned-in caption that always says "curve 100%" is noise
                + (f"curve {state['curve']:.2f}  "
                   if state["curve"] < 0.999 else "")
                + f"zoom {view['zoom']:.1f}x  TGC {self.tgc_lo}-"
                f"{max(self.tgc_lo, self.tgc_hi)}"
                + (f"  cine {self.play_t - self._span():+.2f} s"
                   if state["frozen"] and self.review else "")
                + ("  [FILE REPLAY]" if getattr(self, "debug_offline", False) else ("" if HW else "  [SIM]")))

    def do_capture(self):
        if state["frozen"] and self.review:
            publish_replay_sync(self._review_rf(self.cur_idx))
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
        note = self.debug_note.text()
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            note, ok = QInputDialog.getText(self, "save settings",
                                            "note (what are we looking at?)")
            if not ok:
                return
        if state["frozen"] and self.review and not getattr(self, "debug_loading", False):
            publish_replay_sync(self._review_rf(self.cur_idx))
        path = write_settings(self, note.strip())
        if path is None:
            self.set_lbl.setText("save FAILED - see console")
            self.set_lbl.setStyleSheet(f"color:{WARN_C};")
            return
        self.set_lbl.setText(f"saved settings/{os.path.basename(path)}")
        self.set_lbl.setStyleSheet(f"color:{DIM};")

    # -- frame / status -------------------------------------------------------
    def _tick(self):
        self.debug_tick()
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
            + (f" · freq-comp x{FREQ_COMP_BANDS}" if state["freq_comp"] else "")
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
               or stats["skips"] or stats["bad_sweeps"])
        now = time.perf_counter()
        render_hz = (gl.rendered_images - self.render_count) / max(now - self.render_clock, 1e-6)
        self.render_clock, self.render_count = now, gl.rendered_images
        self.status.setText(
            f" {stats['mbps']:6.1f} MB/s   {stats['sweep_hz']:6.1f} valid sweeps/s"
            f"   {render_hz:.0f} images/s drawn"
            f"   frames {stats['frames']}   drops {stats['drops']}"
            f"   resyncs {stats['resyncs']}"
            f"   holes {stats['seq_bad']}/{stats['seq_chk']}"
            f"   skips {stats['skips']}"
            f"   rejected {stats['bad_sweeps']} sw"
            f"   |  gpu {perf['gpu_ms']:.2f} ms   ui {perf['cpu_ms']:.2f} ms"
            f"   hilbert {perf['hil_ms']:.1f} ms ({FFT_LIB}, off-thread)"
            + ("" if stats["alive"] else "   *** STREAM STOPPED ***"))
        self.status.setStyleSheet(f"color:{WARN_C if bad else OK_C};")

    def closeEvent(self, ev):
        if self.debug_jobs:
            self.debug_label.setText("Wait for the RF file operation to finish before closing")
            ev.ignore()
            return
        stats["alive"] = False
        self.audio.stop()                 # release the device before teardown
        hil_ev.set()                      # let the worker notice and exit
        if HW:
            try:
                send_cmd(cmd(0x10, 0), "disarm_on_close")
                send_cmd(cmd(OP_STOP), "stop")
            except SystemExit:
                pass
            d3.FT_AbortPipe(h, C.c_ubyte(PIPE_IN))
            reader_thread.join(timeout=2)
            if not reader_thread.is_alive():
                for i in range(NBUF):
                    d3.FT_ReleaseOverlapped(h, C.byref(ovs[i]))
                d3.FT_Close(h)
        hilbert_thread.join(timeout=2)
        if self.debug_session:
            self.debug_session.close()
            self.debug_session = None
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
    if REPLAY_PATH:
        QTimer.singleShot(0, lambda: win.debug_open_rf(REPLAY_PATH))
    elif START_SETTINGS is not None:
        def start_settings():
            errors = [None]
            preset = None
            try:
                with open(START_SETTINGS, "r", encoding="utf-8-sig") as stream:
                    preset = json.load(stream)
                win.debug_apply(preset, replay=False)
                if START_ARMED:
                    win.cb_arm.setChecked(True)
            except Exception as exc:
                errors[0] = str(exc)
                win.cb_arm.setChecked(False)
                win.debug_label.setText(f"Settings startup failed; transmit off: {exc}")

            def receipt(verify_live=False):
                evidence = None
                if verify_live and stats["complete_sweeps"] > 0:
                    with cine.lk:
                        items = list(cine.buf)[-8:]
                        quality = list(cine.quality)[-len(items):]
                        if items:
                            first = items[0][0]
                            evidence = ([rf.copy() for _, rf in items],
                                        np.array([t - first for t, _ in items]),
                                        copy.deepcopy(quality))
                if verify_live and HW and START_ARMED and errors[0] is None:
                    from bench_transport import query_firmware
                    try:
                        info = query_firmware(sys.modules[__name__], with_lease=False)
                        win.debug_firmware_info = dict(info,
                            checked_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            note="Disarmed status readback after the settings-preset live interval.")
                        good = (not info.get("pulser_fault") and info.get("pulser_frames", 0) > 0
                                and stats["complete_sweeps"] > 0)
                        if not good:
                            raise RuntimeError("No complete RF flow: pulser_frames=%s fault=%s/%s valid_sweeps=%s"
                                % (info.get("pulser_frames"), info.get("pulser_fault"),
                                   info.get("pulser_fault_code"), stats["complete_sweeps"]))
                        pulser.set_arm(True)
                        evidence_dir = os.path.join(os.path.dirname(os.path.dirname(
                            os.path.abspath(__file__))), "bench_runs")
                        win.scene.gl.grabFramebuffer().save(
                            os.path.join(evidence_dir, "live-settings.png"), "PNG")
                        if evidence is not None:
                            frames, times, quality = evidence
                            acquired = copy.deepcopy(win.debug_epoch or settings_snapshot(win))
                            metadata = {
                                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "acquired_settings": acquired,
                                "review_settings": settings_snapshot(win),
                                "context": {"note": "Guarded settings-preset startup evidence",
                                            "setup": copy.deepcopy(win.debug_setup)},
                                "provenance": win.debug_source,
                                "configuration_boundary": "Preset applied disarmed; verified status and live flow",
                            }
                            rf_path = os.path.join(evidence_dir, "live-settings.rf.npz")
                            reference = mf_reference().copy()
                            def save_evidence():
                                rf_debug.save_session(rf_path, frames, times, metadata,
                                                      quality, reference, None)
                                report = rf_debug.diagnostics(frames, quality,
                                    shot_method=acquired["transmit"].get("shot_method", 0))
                                rf_debug.atomic_json(rf_path + ".report.json", report)
                            win.debug_background_job(save_evidence,
                                "Saved guarded preset PNG + RF evidence")
                    except Exception as exc:
                        errors[0] = str(exc)
                        win.cb_arm.setChecked(False)
                        win.debug_label.setText(errors[0] + "; transmit off")
                path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "bench_runs", "live-settings-startup.json")
                rf_debug.atomic_json(path, {
                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": errors[0],
                    "hardware": HW,
                    "preset": START_SETTINGS,
                    "requested_arm": START_ARMED,
                    "armed": pulser.arm,
                    "firmware": getattr(win, "debug_firmware_info", None),
                    "frames_received": stats["frames"],
                    "valid_sweeps": stats["complete_sweeps"],
                    "settings": settings_snapshot(win),
                })
            QTimer.singleShot(2000, lambda: receipt(False))
            QTimer.singleShot(8000, lambda: receipt(True))
        QTimer.singleShot(0, start_settings)
    elif START_FAST17:
        def start_fast17():
            errors = [None]
            try:
                win.apply_method(FAST17)
                if START_ARMED:
                    win.cb_arm.setChecked(True)
            except Exception as exc:
                errors[0] = str(exc)
                win.cb_arm.setChecked(False)
                win.debug_label.setText(f"Fast 17 cm startup failed; transmit off: {exc}")
            def receipt(verify_live=False):
                evidence = None
                if verify_live and stats["complete_sweeps"] > 0:
                    with cine.lk:
                        items = list(cine.buf)[-8:]
                        quality = list(cine.quality)[-len(items):]
                        if items:
                            t0 = items[0][0]
                            evidence = ([rf.copy() for _, rf in items],
                                        np.array([t - t0 for t, _ in items]),
                                        copy.deepcopy(quality))
                if verify_live and HW and START_ARMED and errors[0] is None:
                    from bench_transport import query_firmware
                    try:
                        info = query_firmware(sys.modules[__name__], with_lease=False)
                        win.debug_firmware_info = dict(info,
                            checked_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            note="Disarmed pulser status readback after the live-flow interval.")
                        good = (not info.get("pulser_fault") and info.get("pulser_frames", 0) > 0
                                and stats["complete_sweeps"] > 0)
                        if good:
                            pulser.set_arm(True)
                            evidence_dir = os.path.join(os.path.dirname(os.path.dirname(
                                os.path.abspath(__file__))), "bench_runs")
                            win.scene.gl.grabFramebuffer().save(
                                os.path.join(evidence_dir, "live-fast17.png"), "PNG")
                            if evidence is not None:
                                frames, times, quality = evidence
                                acquired = copy.deepcopy(win.debug_epoch or settings_snapshot(win))
                                metadata = {
                                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "acquired_settings": acquired,
                                    "review_settings": settings_snapshot(win),
                                    "context": {"note": "Guarded Fast 17 cm startup evidence",
                                                "setup": copy.deepcopy(win.debug_setup)},
                                    "provenance": win.debug_source,
                                    "configuration_boundary": "Verified FPGA readback and live-flow interval",
                                }
                                rf_path = os.path.join(evidence_dir, "live-fast17.rf.npz")
                                reference = mf_reference().copy()
                                def save_evidence():
                                    rf_debug.save_session(rf_path, frames, times, metadata,
                                                          quality, reference, None)
                                    report = rf_debug.diagnostics(frames, quality,
                                        shot_method=acquired["transmit"].get("shot_method", 0))
                                    rf_debug.atomic_json(rf_path + ".report.json", report)
                                win.debug_background_job(save_evidence,
                                    "Saved guarded Fast 17 cm PNG + RF evidence")
                        else:
                            errors[0] = ("No complete RF flow: pulser_frames=%s fault=%s/%s "
                                         "valid_sweeps=%s" % (info.get("pulser_frames"),
                                         info.get("pulser_fault"), info.get("pulser_fault_code"),
                                         stats["complete_sweeps"]))
                            win.cb_arm.setChecked(False)
                            win.debug_label.setText(errors[0] + "; transmit off")
                    except Exception as exc:
                        errors[0] = f"Live status readback failed: {exc}"
                        win.cb_arm.setChecked(False)
                        win.debug_label.setText(errors[0] + "; transmit off")
                path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "bench_runs", "live-startup.json")
                rf_debug.atomic_json(path, {
                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": errors[0],
                    "hardware": HW,
                    "requested_fast17": True,
                    "requested_arm": START_ARMED,
                    "armed": pulser.arm,
                    "method_verified": win.method_verified,
                    "firmware": getattr(win, "debug_firmware_info", None),
                    "frames_received": stats["frames"],
                    "valid_sweeps": stats["complete_sweeps"],
                    "settings": settings_snapshot(win),
                })
            QTimer.singleShot(2000, lambda: receipt(False))
            QTimer.singleShot(8000, lambda: receipt(True))
        QTimer.singleShot(0, start_fast17)
    print("streaming - close the window to stop.")
    sys.exit(app.exec())
