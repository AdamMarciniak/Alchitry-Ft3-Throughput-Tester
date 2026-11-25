"""Measured RF plots and a local comparison report. No hardware access."""
import html
import json
import os
from pathlib import Path

import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QFont,QFontDatabase,QPen,QPainter
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel
from PySide6.QtCharts import QChart,QChartView,QLineSeries,QValueAxis,QLogValueAxis
from PIL import Image

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
d=json.loads((OUT/'analysis.json').read_text())
p=np.load(OUT/'profiles.npz')
app=QApplication.instance() or QApplication([])
font_id=QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
family=QFontDatabase.applicationFontFamilies(font_id)[0]
app.setFont(QFont(family,10))


def chart(title,xlabel,ylabel,xrange,yrange,log=False):
    c=QChart();c.setTitle(title);c.setTitleFont(QFont(family,13))
    x=QValueAxis();x.setRange(*xrange);x.setTickCount(7);x.setTitleText(xlabel)
    y=QLogValueAxis() if log else QValueAxis()
    y.setRange(*yrange);y.setTitleText(ylabel)
    if log:y.setBase(10)
    for axis in (x,y):axis.setLabelsFont(QFont(family,10));axis.setTitleFont(QFont(family,10))
    c.addAxis(x,Qt.AlignBottom);c.addAxis(y,Qt.AlignLeft)
    c.legend().setAlignment(Qt.AlignBottom);c.legend().setFont(QFont(family,10))
    return c,x,y


def series(c,x,y,label,xx,yy,color):
    s=QLineSeries();s.setName(label);s.setPen(QPen(QColor(color),2.5))
    for a,b in zip(xx,yy):s.append(float(a),float(b))
    c.addSeries(s);s.attachAxis(x);s.attachAxis(y)


panel=QWidget();panel.setStyleSheet('background:white;color:#192633')
layout=QVBoxLayout(panel)
title=QLabel('One heart sweep | actual received RF before pulse compression')
title.setFont(QFont(family,17));layout.addWidget(title)
row=QHBoxLayout();layout.addLayout(row)
c,x,y=chart('Depth profile: 2-5 MHz','Equivalent pulse-echo range (cm)','RMS (ADC counts)',(1,18),(.1,100),True)
b=d['bands'][-1]
for label,key,color in [('46 included: median','included_median','#1565c0'),('Excluded 25/46: median','excluded_pair_median','#b74273')]:
    series(c,x,y,label,np.mean(d['depth_gates_mm'],axis=1)/10,b[key],color)
view=QChartView(c);view.setRenderHint(QPainter.Antialiasing);row.addWidget(view)
c,x,y=chart('Spectrum: equivalent range 8-12 cm','Frequency (MHz)','Power density (dB ADC counts squared / Hz)',(1,7),(-100,-45))
f=p['frequency_mhz'];m=(f>=1)&(f<=7)
for label,key,color in [('46 included: median','psd-80-120mm-included','#1565c0'),('Excluded 25/46: median','psd-80-120mm-excluded','#b74273')]:
    series(c,x,y,label,f[m],10*np.log10(np.maximum(p[key][m],1e-20)),color)
view=QChartView(c);view.setRenderHint(QPainter.Antialiasing);row.addWidget(view)
foot=QLabel('Signal plus noise, not tissue SNR. Excluded channels are imperfect noise controls. Depth is time converted at 1540 m/s, before geometry correction.')
layout.addWidget(foot);panel.resize(1600,620);panel.show();app.processEvents()
assert panel.grab().save(str(OUT/'rf-measurements.png'));panel.close()
p.close()

options=''.join(f'<option value="{r["name"]}">{html.escape(r["title"])}</option>' for r in d['renders'])
rows=[]
for i in range(3,len(d['depth_gates_mm'])):
    lo,hi=d['depth_gates_mm'][i]
    rows.append(f'<tr><td>{lo/10:g}-{hi/10:g} cm</td><td>{b["included_median"][i]:.3f}</td><td>{b["excluded_pair_median"][i]:.3f}</td></tr>')
gallery=''.join(f'<figure><a href="{r["name"]}/axes.png"><img loading="lazy" src="{r["name"]}/matched.png" alt="{html.escape(r["title"])}"></a><figcaption>{html.escape(r["title"])} · <a href="{r["name"]}/settings.json">settings</a> · <a href="{r["name"]}/trial.json">method</a></figcaption></figure>' for r in d['renders'])
doc='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Heart chirp RF review — September 9</title><style>
body{font:16px/1.55 system-ui,sans-serif;max-width:1400px;margin:30px auto;padding:0 20px;background:#f3f6f8;color:#172939}h1{font-size:31px;line-height:1.2}h2{margin-top:32px}a{color:#1265a9}figure{margin:0;background:white;padding:10px;border:1px solid #d7e0e6;border-radius:8px}img{width:100%;display:block}figcaption{font-size:14px;margin-top:7px}.two,.gallery{display:grid;gap:14px;grid-template-columns:repeat(2,minmax(0,1fr))}.gallery{grid-template-columns:repeat(3,minmax(0,1fr))}select{font:inherit;padding:8px;max-width:100%;margin:8px 0}.notice{background:#e5eef7;border-left:4px solid #1765a9;padding:16px}table{border-collapse:collapse;background:white;width:100%}td,th{padding:8px;border-bottom:1px solid #d7e0e6;text-align:left}code{overflow-wrap:anywhere}small{color:#516171}@media(max-width:700px){.two,.gallery{grid-template-columns:1fr}}
</style><h1>Compression was enabled; the remaining blur is not explained by a missing checkbox</h1>
<p>September 9, 2026 · <code>host/heart-chirp.rf.npz</code> · one complete sweep, 48 × 9090 RF samples. The matching screenshot is <code>host/settings/20260909_140323_711624200.png</code>. All work here is offline.</p>
<p class="notice"><b>The file contains useful deep echoes, but these comparisons do not establish resolved chamber walls.</b> Thirteen reconstructions were inspected. Pulse compression gives finer axial texture in parts of the image; lateral arcs remain. No tested decoder demonstrated a convincing anatomical recovery. A single sweep cannot separate heart/probe motion, aberration, reverberation and hardware timing effects.</p>
<h2>Compare the same RF</h2><p>Choose two variants. “Matched brightness” applies a single scalar offset to match the 90th-percentile normalized magnitude in the fixed central region (±25 mm lateral, 40–140 mm depth). It helps compare structure; it is not an SNR measurement. Both images use a common 100 dB / +12 dB display in that mode. No local contrast enhancement or generated detail is used.</p>
<label><input id="equal" type="checkbox" checked> Matched brightness</label>
<div class="two"><div><select id="left">OPTIONS</select><figure><img id="left-image" alt="Left selected RF reconstruction"></figure></div><div><select id="right">OPTIONS</select><figure><img id="right-image" alt="Right selected RF reconstruction"></figure></div></div>
<p>The uncompressed view requires a −15.85 dB comparison offset. The host normalizes its matched filter by reference energy; raw and compressed amplitudes therefore differ. This offset must not be reported as 15.85 dB of SNR gain.</p>
<h2>What is verified</h2><ul>
<li><b>Compression on, chirp 0.5 → 8 MHz, requested 4.5 µs / quantized burst 4.48 µs.</b> Receive 2–5 MHz, TGC 1000 → 3678, receive delay 16 µs, 21% apodization, coherence factor off, one-sweep averaging. Nominal sequential aperture: 28.09 ms.</li>
<li><b>The 179-sample saved reference exactly matches the current command generator.</b> This excludes a stale duration/reference mismatch in file replay. It does not measure the pulser waveform or the probe/AFE phase response, and does not identify the running bitstream.</li>
<li><b>No ADC clipping:</b> extrema −266 and +279 counts, well inside the 12-bit rails. All 48 element records are complete. Historical stream resync counters do not imply this saved sweep is incomplete.</li>
<li><b>Only 41.1% of the saved electrical reference energy is in 2–5 MHz.</b> 54.3% is in 2–6 MHz. These are discrete commanded-waveform spectrum fractions, not measured acoustic energy or receiver transfer functions. An ideal 0.5–8 MHz linear sweep spends approximately 1.8 µs of its 4.5 µs duration in 2–5 MHz.</li>
</ul>
<h2>Received RF has energy above the rough noise comparison</h2><figure><img src="rf-measurements.png" alt="Measured RF depth profile and spectrum"></figure>
<table><tr><th>Equivalent range</th><th>Included-channel median RMS</th><th>Excluded-pair median RMS</th></tr>ROWS</table>
<p><small>ADC counts. Fourth-order Butterworth 2–5 MHz filter with zero-phase forward/backward filtering, applied only for these measurements. The reconstructed images use the production receive filter. Channels 25/46 have different electrical terminations and are not calibrated noise references.</small></p>
<p>At 10–12 cm the median is 3.79 counts versus 0.42 for the excluded pair. This makes “nothing but the ADC floor at all depths” an inadequate explanation for this recording. The excess can contain tissue echoes, reverberation and clutter; it does not prove that the broad bright regions are chamber walls. Most deep excess power is around 2–4 MHz; 5–6 MHz is close to the excluded-channel spectrum. Position and acquisition settings changed from older clips, so this is not a controlled measurement of chirp benefit.</p>
<h2>What the processing trials show</h2><ul>
<li><b>Saved decoder versus off:</b> some finer axial features with compression, persistent lateral arcs. This is a visual observation on unknown reflectors, not a measured point-spread function.</li>
<li><b>2–4 MHz:</b> a reasonable deep-echo viewing band for this RF. It removes frequencies carrying relatively little deep excess energy, but gives up bandwidth and can widen axial detail.</li>
<li><b>75% apodization:</b> changes and softens off-axis contributions, without removing the broad arcs. Keep coherence suppression off for the faint-echo review; increasing it preferentially darkens weakly coherent content.</li>
<li><b>Frequency compounding:</b> smoother texture with coarser detail. It does not establish additional resolved tissue.</li>
<li><b>Four offline decoder experiments:</b> two regularized inverse filters, a Hann spectral weighting, and a continuous-time pulse-edge reference. None gave a clear enough benefit to replace production decoding. Experimental settings JSON files describe the surrounding host configuration only; <code>analyze.py</code> implements those extra filters.</li>
</ul>
<p>The central-region coherence median was 0.0144 (90th percentile 0.0624). This indicates weak phase agreement over much of that region, but the statistic mixes many scatterers, noise and clutter. It cannot by itself identify a timing defect or quantify motion.</p>
<h2>A replay option, not a validated tissue preset</h2><p>Keep pulse compression on, receive 2–4 MHz, apodization 75%, coherence 0, averaging 1. A display of 85 dB range / +27 dB gain makes the broad echoes easier to inspect. It does not recover new RF information. <a href="review/axes.png">View it</a> or use the <a href="review/settings.json">saved configuration</a>. In a frozen RF review, change these processing controls directly; the host's acquisition-settings loader requires a new live run.</p>
<h2>The next useful experiment is a fixed wire calibration</h2><p>On the water bench, compare the existing broad chirp with a 2–5 MHz chirp at the same duration and peak drive, and include a short-pulse reference. Keep the wire, gain, delay and receive processing fixed. Save complete RF for each. Measure axial width, range sidelobes and background level before choosing a waveform. Concentrating the sweep in the useful band is a testable hypothesis; its actual benefit and acoustic output have not been measured here.</p>
<p>Use an isolated, unsaturated wire return to estimate the actual echo waveform and its delay. Then compare the commanded-reference filter with a measured-response matched or regularized mismatched filter. Do not learn a supposedly “correct” pulse from an unidentified heart echo: overlapping reflectors and reverberation would be absorbed into that calibration. Pulse-compression design needs to account for transducer response and the resolution/sidelobe tradeoff; see <a href="https://pubmed.ncbi.nlm.nih.gov/15801308/">Misaridis &amp; Jensen, 2005</a>.</p>
<p>No FPGA or production-host algorithm change is justified by these results alone. Receive capture begins after this 4.48 µs transmit burst, so direct burst overlap is not indicated by the requested timing. Analog recovery still needs measurement. The 28.09 ms sequential aperture remains a possible motion limitation, and one exported frame contains no time sequence with which to estimate it.</p>
<h2>All trials</h2><p>Gallery uses matched brightness. Click an image for its saved display. Experimental cases are explicitly labeled.</p><div class="gallery">GALLERY</div>
<h2>Reproduce</h2><p><a href="analyze.py">SIM-only analysis and reconstruction</a> · <a href="analysis.json">Measurements and source hash</a> · <a href="profiles.npz">Spectra and channel envelopes</a> · <a href="report.py">Report builder</a>. Each trial includes linear magnitude, settings and method metadata. Source RF and its screenshot remain unchanged; no hardware connection or programming was used.</p>
<script>const a=document.getElementById('left'),b=document.getElementById('right'),e=document.getElementById('equal');a.value='saved';b.value='off';function update(){for(const id of ['left','right'])document.getElementById(id+'-image').src=document.getElementById(id).value+'/'+(e.checked?'matched.png':'axes.png')}a.onchange=b.onchange=e.onchange=update;update();</script></html>'''
doc=doc.replace('OPTIONS',options).replace('ROWS',''.join(rows)).replace('GALLERY',gallery)
(OUT/'report.html').write_text(doc,encoding='utf-8')
im1=Image.open(OUT/'saved/axes.png');im2=Image.open(OUT/'review/axes.png')
comparison=Image.new('RGB',(im1.width+im2.width,max(im1.height,im2.height)),'#111820')
comparison.paste(im1,(0,0));comparison.paste(im2,(im1.width,0));comparison.save(OUT/'saved-vs-review.png')
print('Saved report.html, rf-measurements.png, and saved-vs-review.png')
