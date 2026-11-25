"""Build the measured three-clip comparison; no hardware or RF mutations."""
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
from analyze import OUT,ROOT,SOURCES,atomic_json,validate_settings

data={name:json.loads((OUT/f'{name}-analysis.json').read_text()) for name in SOURCES}
app=QApplication.instance() or QApplication([])
font_id=QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
family=QFontDatabase.applicationFontFamilies(font_id)[0]
app.setFont(QFont(family,10))
panel=QWidget();panel.setStyleSheet('background:white;color:#192633')
layout=QVBoxLayout(panel)
title=QLabel('Three heart clips | measured RF amplitude with the same 2-5 MHz analysis filter')
title.setFont(QFont(family,17));layout.addWidget(title)
row=QHBoxLayout();layout.addLayout(row)
for quiet in [False,True]:
    chart=QChart();chart.setTitle('Median across 46 included channels' if not quiet else 'Quiet pair: channels 25 and 46')
    chart.setTitleFont(QFont(family,13))
    x=QValueAxis();x.setRange(1,17);x.setTickCount(9);x.setTitleText('Equivalent pulse-echo range (cm)')
    y=QValueAxis() if quiet else QLogValueAxis()
    if quiet:y.setRange(.25,.75);y.setTickCount(6)
    else:y.setBase(10);y.setRange(.1,100)
    y.setTitleText('Filtered RMS (ADC counts)')
    chart.addAxis(x,Qt.AlignBottom);chart.addAxis(y,Qt.AlignLeft)
    for axis in [x,y]:axis.setLabelsFont(QFont(family,10));axis.setTitleFont(QFont(family,10))
    for name,color in [('baseline','#1565c0'),('start','#18865b'),('tgc','#aa3e73')]:
        d=data[name];b=d['bands'][0]
        series=QLineSeries();series.setName(name.capitalize());series.setPen(QPen(QColor(color),2.5))
        for xx,yy in zip(np.mean(d['depth_gates_mm'],axis=1)/10,b['quiet_pair_median_rms' if quiet else 'included_channel_median_rms']):
            series.append(float(xx),float(yy))
        chart.addSeries(series);series.attachAxis(x);series.attachAxis(y)
    chart.legend().setAlignment(Qt.AlignBottom);chart.legend().setFont(QFont(family,10))
    view=QChartView(chart);view.setRenderHint(QPainter.Antialiasing);row.addWidget(view)
foot=QLabel('64 evenly spaced sweeps per clip. Probe movement limits between-clip conclusions. The quiet pair is not a calibrated noise-only reference.')
layout.addWidget(foot);panel.resize(1700,650);panel.show();app.processEvents()
assert panel.grab().save(str(OUT/'depth-comparison.png'));panel.close()

rows=[]
for name,d in data.items():
    rows.append(f'<tr><td>{name.capitalize()}</td><td>{d["shape"][0]}</td><td>{d["duration_s"]:.2f} s</td><td>{d["valid_frames"]}</td><td>{d["clipped_samples_total"]}</td><td>{d["settings"]["acquisition"]["tgc_min"]} to {d["settings"]["acquisition"]["tgc_max"]}</td></tr>')
depth_rows=[]
for i in [4,5,6,7,8,9]:
    gate=data['baseline']['depth_gates_mm'][i]
    values=[]
    for d in data.values():
        b=d['bands'][0];values.append(f'{b["included_channel_median_rms"][i]:.3f} / {b["quiet_pair_median_rms"][i]:.3f}')
    depth_rows.append(f'<tr><td>{gate[0]/10:g}-{gate[1]/10:g} cm</td>'+''.join(f'<td>{v}</td>' for v in values)+'</tr>')
gallery=[]
for name in SOURCES:
    figures=[]
    for p in sorted(OUT.glob(f'{name}-common-f*'),key=lambda p:int(p.name.split('-f')[-1])):
        figures.append(f'<figure><a href="{p.name}/image-axes.png"><img loading="lazy" src="{p.name}/image-axes.png" alt="{p.name}"></a><figcaption>RF frame {p.name.split("-f")[-1]}</figcaption></figure>')
    gallery.append(f'<h3>{name.capitalize()}</h3><div class="five">'+''.join(figures)+'</div>')
doc='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Heart preset comparison</title>
<style>body{font:16px/1.55 system-ui,sans-serif;background:#f3f6f8;color:#1a2633;max-width:1320px;margin:30px auto;padding:0 20px}h1{font-size:30px;line-height:1.2}h2{font-size:23px;margin-top:32px}a{color:#1265a9}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:9px;border-bottom:1px solid #d9dfe5}figure{margin:0;padding:10px;background:white;border:1px solid #d9dfe5;border-radius:8px}img{width:100%;display:block}.three,.five{display:grid;gap:14px;grid-template-columns:repeat(3,1fr)}.five{grid-template-columns:repeat(5,1fr)}figcaption{font-size:14px;margin-top:7px}.notice{background:#e7eef8;padding:16px;border-left:4px solid #1565c0}code{overflow-wrap:anywhere}small{color:#526172}@media(max-width:900px){.five{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.three,.five{grid-template-columns:1fr}}</style>
<h1>The gain ramp changes the recording; a clear tissue-image improvement is not established</h1>
<p>September 9, 2026. Three user-recorded clips: 504 complete sweeps, zero clipped ADC samples. RF hashes and archive CRCs verified. All analysis used existing files offline; no physical acquisition or programming occurred.</p>
<p class="notice"><b>The comparison is limited by probe movement.</b> The user reports some movement between presets, with an uncertain amount. Previous context also includes rib shadowing. The three views are not controlled repeats, and the heart itself is moving. These results do not isolate an electronics fault or establish an optimal preset.</p>
<h2>Comparable cine previews</h2><p>Each uses exactly the same reconstruction/display: 2-5 MHz, CF off, one sweep, 75% apodization, channels 25/46 excluded, 95 dB / +15 dB, curve 1. Previews sample every fourth RF sweep at approximately real time. The clips loop independently; corresponding displayed moments are not synchronized cardiac phases.</p>
<div class="three"><figure><img src="baseline-common.gif" alt="Baseline RF replay"><figcaption>Baseline: flat TGC 1600.</figcaption></figure><figure><img src="start-common.gif" alt="Start RF replay under the common display"><figcaption>Start: same acquisition as baseline; display differences removed here.</figcaption></figure><figure><img src="tgc-common.gif" alt="TGC RF replay under the common display"><figcaption>TGC: 1000 to 3400, common display.</figcaption></figure></div>
<h2>What was actually recorded</h2><table><tr><th>Clip</th><th>Sweeps</th><th>Duration</th><th>Valid</th><th>Clipped samples</th><th>TGC</th></tr>ROWS</table>
<p>All three use 48 elements, 8020 samples per element at 40 MSPS, a 16 µs receive offset, 313 µs gap and the same commanded chirp. The aperture period is nominally 26.64 ms. Manual metadata still lacks runtime bitstream/register readback. Large lifetime timeout/resync counters do not describe losses within these selected clips: each saved sweep is complete.</p>
<p><b>Start is a processing/display alternative.</b> It changes the band from 2-5 to 2-4 MHz and the display from 95 dB / +15 dB to 80 dB / +30 dB. It does not increase acquisition sensitivity. The TGC clip's saved review curve was additionally changed from 1 to 0.67; that difference is removed in the common comparisons.</p>
<h2>Depth-resolved RF</h2><figure><img src="depth-comparison.png" alt="RF amplitude and quiet-channel power across depth"><figcaption>The TGC quiet-channel level rises with depth, consistent with the gain ramp taking effect. This does not measure the actual control voltage or prove better input SNR.</figcaption></figure>
<table><tr><th>Equivalent range</th><th>Baseline</th><th>Start</th><th>TGC</th></tr>DEPTHROWS</table><p><small>Each entry: median RMS of the 46 included channels / median RMS of quiet channels 25 and 46, in ADC counts. A fourth-order Butterworth analysis filter and 64 evenly spaced valid sweeps are used per clip. These are signal-plus-noise measurements, not beamformed SNR or verified anatomical depths.</small></p>
<p>The TGC clip has much more energy near 5-6 cm, but baseline has more near 10-12 cm. Near 14-16 cm, TGC raises the quiet comparison from about 0.32 to 0.66 counts while the included-channel median is only 0.73. Much of that far-field brightness is therefore consistent with amplified noise. Neither the amplitude differences nor the images establish a uniform tissue benefit.</p>
<p>The original longer recording had about 0.35 counts RMS at 10-12 cm, compared with 0.95 in this new baseline clip at the same nominal acquisition settings. That demonstrates substantial capture-to-capture variation, not a fixed absence of signal at that range. The RF alone does not identify the reflector or why its visibility changed.</p>
<h2>Image and motion findings</h2><p>There are broad echoes and arcs in these clips, but no convincing chamber boundaries were established by the replay comparisons. Additional gray level and a smoother-looking texture are not sufficient evidence of resolved tissue. No anatomical labels or health conclusions are assigned.</p>
<p>A bounded RF time-shift check improved some adjacent-frame correlations, but did not reveal a reliable global motion correction. In TGC at 8-12 cm, the median best-shift correlation was approximately 0.19, versus 0.16 for the quiet controls; the search itself increases random correlations. In the 4-6 cm gate it rose from 0.014 at zero lag to 0.36, but remains variable. These statistics mix motion, noise and changing scatterers and do not establish velocity or prove a timing bug.</p>
<h2>What to do next</h2><ul><li>Keep the current baseline and TGC files as references. This comparison is not a basis for increasing the TGC endpoint further or calling one preset optimized.</li><li>Use Start for its 2-4 MHz/grayscale presentation if it is easier to view. Its acquisition is identical to baseline, and filtering can be compared on the same saved RF without another scan.</li><li>The next useful engineering experiment is on the fixed water bench: verify the actual AFE gain ramp and connected-channel noise, then assess complete sweeps and focusing while shortening the sequential aperture. The current 26.64 ms aperture remains a possible motion limit; it has not been isolated here. Earlier short-gap tests lost elements, so a timing change requires a transport/settling check.</li><li>If a later manual tissue comparison is made, use a supported, unchanged probe position and baseline-TGC-baseline order. Keep processing fixed and save RF. That checks whether a view change or drift is dominating the apparent gain benefit.</li></ul>
<p>The <a href="../../host/presets/heart-tgc-next-test.json">TGC preset</a> now records this limited validation: 189 complete user-recorded sweeps, no clipping, gain-dependent noise increase, no proven tissue-image improvement. Its operational settings remain unchanged.</p>
<h2>Static comparisons across each clip</h2>GALLERY
<h2>Reproducibility</h2><p><a href="baseline-analysis.json">Baseline RF measurements</a> · <a href="start-analysis.json">Start RF measurements</a> · <a href="tgc-analysis.json">TGC RF measurements</a> · <a href="../../docs/heart-preset-comparison-2026-09-09.md">Detailed comparison notes</a></p>
<p>Each rendered still has saved settings, a linear magnitude array and trial metadata. Cine JSON files list frame indices, display settings, source hashes and timing. The 21 still renders and 127 cine preview frames use the production receive pipeline and shaders. Wire-specific metrics automatically emitted by the harness were not used as tissue-contrast scores. Source files were read-only and remain unchanged.</p></html>'''
doc=doc.replace('ROWS</table>',''.join(rows)+'</table>',1).replace('DEPTHROWS',''.join(depth_rows)).replace('GALLERY',''.join(gallery))
(OUT/'report.html').write_text(doc,encoding='utf-8')
context={'user_report':'Some probe movement between clips; unsure how much. Prior recording context included rib shadowing.',
         'acquisition_source':'User-recorded clips; assistant performed only offline analysis',
         'clips':{k:{'source':v['source'],'rf_sha256':v['rf_sha256'],'shape':v['shape']} for k,v in data.items()}}
atomic_json(OUT/'comparison-context.json',context)
path=ROOT/'host/presets/heart-tgc-next-test.json'
preset=json.loads(path.read_text());before=validate_settings(preset)
preset['note']='Compared in 189 complete user-recorded heart sweeps with zero ADC clipping. Only acquisition change from the baseline preset is TGC1000->3400. Gain-dependent noise increase is visible, but probe movement prevents a controlled tissue-image comparison. No clear tissue benefit established; operational settings remain a test profile.'
preset['validation']={'status':'Limited manual-capture validation; not an optimized tissue preset',
    'study':'docs/heart-preset-comparison-2026-09-09.md','source':data['tgc']['source'],
    'rf_sha256':data['tgc']['rf_sha256'],'complete_sweeps':189,'clipped_adc_samples':0,
    'limitations':['Probe position varied by an uncertain amount','Manual capture lacks hardware configuration readback',
                  'Analog control-voltage waveform not measured','No uniform deep-detail improvement established']}
assert validate_settings(preset)==before
atomic_json(path,preset)
print('Built comparison report and updated only TGC preset validation metadata.')
