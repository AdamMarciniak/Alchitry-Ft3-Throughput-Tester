"""Build a local engineering report and disarmed presets from measured RF results."""
import copy
import html
import json
import os
import sys
from pathlib import Path

import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPen, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QLogValueAxis

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'host'))
from rf_debug import atomic_json, validate_settings

analysis = json.loads((OUT / 'rf-analysis.json').read_text())
base = validate_settings(analysis['settings'])
base['settings_schema'] = 1
base['provenance'] = {
    'source_recording': analysis['source'],
    'rf_sha256': analysis['rf_sha256'],
    'report': 'docs/heart-rf-review-2026-09-09.md',
    'runtime_fpga_identity': 'Not read back in this manual recording',
    'load_behavior': 'Loading settings leaves transmit disarmed',
}
base['note'] = 'Exact operational settings from the heart recording, restored disarmed. Comparison baseline; no image-quality validation.'
atomic_json(ROOT / 'host/presets/heart-recording-baseline.json', base)
review = copy.deepcopy(base)
review['receive'].update(band_f0_mhz=3, band_bw_mhz=2)
review['display'].update(dyn_db=80, gain_db=30)
review['note'] = 'Offline-reviewed display alternative: 2-4 MHz, 80 dB / +30 dB. Makes weak grain easier to inspect; did not recover convincing chamber detail. Acquisition stays flat TGC1600. In file replay, set these receive/display controls directly; GUI settings-file loading is available in new live run.'
atomic_json(ROOT / 'host/presets/heart-review-start.json', review)
next_test = copy.deepcopy(base)
next_test['acquisition'].update(tgc_min=1000, tgc_max=3400)
next_test['note'] = 'UNTESTED acquisition comparison. Only change from heart-recording-baseline is analog TGC1000->3400 across the receive window. No hardware was operated to validate this preset. Keep the same waveform, voltage, timing and reconstruction for the comparison. Verify the analog ramp on the bench; compare clipping and deep signal/noise before drawing conclusions.'
next_test['validation'] = {'status': 'Settings load checked in simulation only; analog response and image improvement untested'}
atomic_json(ROOT / 'host/presets/heart-tgc-next-test.json', next_test)

good = [i for i in range(48) if i not in (25, 46)]
app = QApplication.instance() or QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
assert font_id >= 0, 'Unable to load the report font'
family = QFontDatabase.applicationFontFamilies(font_id)[0]
app.setFont(QFont(family, 10))
panel = QWidget()
panel.setStyleSheet('background:white;color:#18212b')
layout = QVBoxLayout(panel)
title = QLabel('Heart RF review | recorded amplitude and proposed analog gain')
title.setFont(QFont(family, 17))
layout.addWidget(title)
row = QHBoxLayout()
layout.addLayout(row)
charts = []
for i, heading in enumerate(['Recorded RF approaches quiet-channel level', 'Untested TGC proposal: 1000 to 3400']):
    chart = QChart()
    chart.setTitle(heading)
    chart.setTitleFont(QFont(family, 13))
    x = QValueAxis()
    x.setRange(1, 17)
    x.setTickCount(9)
    x.setTitleText('Equivalent pulse-echo range (cm)')
    y = QLogValueAxis() if i == 0 else QValueAxis()
    if i == 0:
        y.setBase(10)
        y.setRange(.1, 100)
        y.setTitleText('Filtered RMS (ADC counts)')
    else:
        y.setRange(-10, 25)
        y.setTickCount(8)
        y.setTitleText('Estimated change vs. flat 1600 (dB)')
    chart.addAxis(x, Qt.AlignBottom)
    chart.addAxis(y, Qt.AlignLeft)
    for axis in [x, y]:
        axis.setLabelsFont(QFont(family, 9))
        axis.setTitleFont(QFont(family, 10))
    chart.legend().setAlignment(Qt.AlignBottom)
    chart.legend().setFont(QFont(family, 9))
    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    row.addWidget(view)
    charts.append((chart, x, y))

def line(index, xx, yy, label, color, dashed=False):
    chart, x, y = charts[index]
    s = QLineSeries()
    s.setName(label)
    s.setPen(QPen(QColor(color), 2.3, Qt.DashLine if dashed else Qt.SolidLine))
    for a, b in zip(xx, yy):
        s.append(float(a), float(b))
    chart.addSeries(s)
    s.attachAxis(x)
    s.attachAxis(y)

for band, color in [([2, 5], '#1565c0'), ([2, 4], '#d06400')]:
    b = next(v for v in analysis['band_depth_measurements'] if v['band_mhz'] == band)
    depth = np.mean(b['depth_bins_mm'], axis=1) / 10
    rms = np.array(b['rms_counts_by_depth_channel'])
    healthy = np.median(rms[:, good], axis=1)
    quiet = np.median(rms[:, [25, 46]], axis=1)
    line(0, depth, healthy, f'{band[0]}-{band[1]} MHz: 46 channels', color)
    line(0, depth, quiet, f'{band[0]}-{band[1]} MHz: quiet pair', color, True)
depth = np.linspace(1.232, 16.6705, 200)
code = 1000 + 2400 * (depth - depth[0]) / (depth[-1] - depth[0])
line(1, depth, (code - 1600) * 1.2 / 4095 * 44.4, 'Nominal estimate; not measured', '#7b4695')
line(1, [1, 17], [0, 0], 'Captured flat-gain baseline', '#888888', True)
foot = QLabel('Left: 64 sweeps; channel medians; quiet pair is not a calibrated noise floor. Right: nominal DAC/AFE model.')
foot.setFont(QFont(family, 10))
layout.addWidget(foot)
panel.resize(1700, 640)
panel.show()
app.processEvents()
assert panel.grab().save(str(OUT / 'depth-signal-and-proposed-gain.png'))
panel.close()

trials = sorted(p.parent for p in OUT.glob('*/trial.json'))
cards = []
for p in trials:
    t = json.loads((p / 'trial.json').read_text())
    patch = json.dumps(t['patch'], sort_keys=True)
    cards.append(f'<figure><a href="{p.name}/image-axes.png"><img loading="lazy" src="{p.name}/image-axes.png" alt="{html.escape(p.name)}"></a><figcaption><b>{html.escape(p.name)}</b> | frame {t["frame"]}<pre>{html.escape(patch)}</pre></figcaption></figure>')
document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Heart RF engineering review</title>
<style>body{font:16px/1.55 system-ui,sans-serif;background:#f4f6f8;color:#18212b;max-width:1250px;margin:30px auto;padding:0 20px}h1{font-size:30px;line-height:1.2}h2{font-size:23px;margin-top:36px}a{color:#1565a9}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;border-bottom:1px solid #ddd;padding:10px}figure{margin:0;background:white;padding:12px;border:1px solid #d8dfe4;border-radius:8px}img{display:block;width:100%;height:auto}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}small{color:#465464}.notice{background:#e7eef8;padding:16px;border-left:4px solid #1565a9}@media(max-width:800px){.gallery{grid-template-columns:1fr 1fr}.pair{grid-template-columns:1fr}}@media(max-width:480px){.gallery{grid-template-columns:1fr}}</style>
<h1>The deeper recording is weak before display processing</h1>
<p>Engineering review of <b>heart-recording.rf.npz.rf.npz</b>, recorded September 9, 2026 at 09:58 local. 956 sweeps, 48 elements, 8020 samples per element, 25.53 seconds. All processing here replayed the existing file; no physical acquisition or programming occurred.</p>
<p class="notice"><b>No convincing chamber detail was recovered.</b> The alternatives change brightness and grain, but do not establish that useful deeper cardiac structure was captured. The user's observation of mostly faint speckle matches these reconstructions. This report does not interpret heart health.</p>
<p><b>Additional capture context:</b> the user was moving the probe slightly to find a view and reports that ribs sometimes blocked the deep signal. Motion and acoustic shadowing are therefore major confounders. The RF does not isolate an electronics fault or prove that gain alone will help. The system is currently off; the user will make the next recordings manually.</p>
<div class="pair"><figure><img src="original-f480/image-axes.png" alt="Original settings, frame 480"><figcaption>Original: 2-5 MHz, 95 dB / +15 dB, coherence weighting off.</figcaption></figure><figure><img src="review-f480/image-axes.png" alt="Brighter narrow-band replay of the same RF"><figcaption>Same RF: 2-4 MHz, 80 dB / +30 dB. More visible grain does not establish more tissue detail.</figcaption></figure></div>
<h2>What the recording establishes</h2><table><tr><th>Check</th><th>Result</th><th>Implication</th></tr>
<tr><td>RF integrity</td><td>956 / 956 complete sweeps; RF SHA-256 and ZIP CRC verified</td><td>No structural data loss found.</td></tr>
<tr><td>ADC clipping</td><td>7 samples, frames 27-29, about 14 mm</td><td>Widespread clipping does not explain the faint image.</td></tr>
<tr><td>Analog TGC</td><td>1600 at both ends of the window</td><td>The capture used flat gain with depth.</td></tr>
<tr><td>Deep RF, 2-5 MHz</td><td>8-12 cm: approximately 0.35 ADC count RMS; quiet pair approximately 0.32</td><td>Very little amplitude margin above the quiet-channel comparison.</td></tr>
<tr><td>Sequential aperture</td><td>26.64 ms commanded for 48 elements</td><td>Motion sensitivity remains a possible additional limit.</td></tr></table>
<p>Depth statistics use 64 evenly spaced sweeps and a fourth-order Butterworth analysis filter. They are median per-channel RMS values, not beamformed SNR. Channels 25 and 46 are a quiet comparison, not a calibrated noise-only measurement for every other channel. Range assumes 1540 m/s and the saved delay; it is not an anatomical depth assignment.</p>
<figure><img src="depth-signal-and-proposed-gain.png" alt="RF amplitude by range, and the proposed analog gain change"><figcaption>Gain estimate uses the reported 0-1.2 V DAC span and the AFE5804 nominal 44.4 dB/V slope in its linear region. The actual ramp and acoustic response have not been measured for this proposal. <a href="https://www.ti.com/lit/ds/symlink/afe5804.pdf">TI AFE5804 datasheet</a>.</figcaption></figure>
<h2>The next useful comparison</h2>
<p>First verify the receive-gain ramp on the water bench. Then compare the baseline against <b>TGC 1000 to 3400</b>, keeping the waveform, voltage, timing, band, coherence setting and display identical. This lowers shallow gain and raises deeper gain before digitization. It can help if ADC/downstream noise is limiting; it also amplifies front-end noise and cannot compensate for a poor acoustic window or missing echoes.</p>
<ul><li><a href="../../host/presets/heart-recording-baseline.json">Captured baseline, disarmed</a></li><li><a href="../../host/presets/heart-tgc-next-test.json">Untested TGC comparison, disarmed</a></li><li><a href="../../host/presets/heart-review-start.json">Optional 2-4 MHz review/display alternative</a></li></ul>
<p>In the TFM host, choose <b>new live run</b>, then <b>load settings...</b> to load an acquisition preset. Loading leaves PULSER RUN off. Recorded RF retains its original analog gain: loading a new acquisition preset cannot change old samples. In file replay, the review alternative can be set directly with band center 3 MHz, bandwidth 2 MHz, dynamic range 80 dB and gain +30 dB.</p>
<p>For the user's next manual comparison, find a clear acoustic window and hold the probe still while recording each setting from the same position. A single frame is useful; a short stationary clip allows persistence and noise checks. Success is repeatable structure above background, not merely a brighter image. Save RF from both conditions and check clipping across all frames, depth-resolved power, and noise measured on connected channels under matched conditions. If increased analog gain only lifts noise, investigate coupling/window and probe/mux/protection/front-end sensitivity before further image cosmetics.</p>
<p>Keep coherence weighting off and averaging at one sweep for that comparison. The existing FPGA supports a linear TGC ramp, so no new firmware is required for this test. Faster sequential acquisition or motion compensation is a later experiment; the earlier short-gap water trial lost elements, so simply reducing the current gap is not validated. Motion during synthetic aperture acquisition can degrade focusing (<a href="https://pubmed.ncbi.nlm.nih.gov/12199420/">primary motion-compensation study</a>); this file does not isolate that effect from low SNR.</p>
<h2>Replay comparisons</h2><p>COUNT renders, including multiple frames, display/band changes, coherence weighting, frequency compounding, matched filtering, two-sweep averaging, apodization and central-aperture subsets. The wire-specific metrics saved by the harness are not valid tissue-contrast scores and were not used to rank this capture. Subset brightness also changes with normalization. Image captions saying “hardware” refer to the original recording source, not a new hardware run; “weighted” is the renderer mode label and the baseline CF exponent is zero.</p><div class="gallery">CARDS</div>
<h2>Reproducibility and limitations</h2><p><a href="rf-analysis.json">Depth/band measurements and RF hash</a> · <a href="temporal-analysis.json">Temporal statistics and clipping locations</a> · <a href="../../docs/heart-rf-review-2026-09-09.md">Detailed notes and test sequence</a></p>
<p>Manual capture metadata does not identify the running bitstream through hardware readback. The saved chirp is enabled; the fixed-burst cycle/width fields do not shorten the chirp in the current RTL. The commanded reference lasts 1.04 microseconds; this is not a measurement of the emitted acoustic pulse. Historical water/wire metadata is not a description of the heart acquisition.</p>
<p>The host loader was updated to read ordinary RF archives through a read-only memory map, avoiding another 737 MB disk copy. Complete RF checksum/CRC checks remain enabled. The bench startup also handles immediate Windows PID reuse. The 52 host tests passed without hardware.</p></html>'''
document = document.replace('COUNT', str(len(trials))).replace('CARDS', ''.join(cards))
(OUT / 'report.html').write_text(document, encoding='utf-8')
print(f'Built report with {len(trials)} renders and three disarmed settings presets.')
