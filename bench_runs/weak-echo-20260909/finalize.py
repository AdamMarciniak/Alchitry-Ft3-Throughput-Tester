"""Write reviewable presets and the evidence report. Never arms hardware."""
from study import *
from rf_debug import load_settings
import html

base=json.loads((ROOT/'host/presets/wire-21c-1mm-das.json').read_text())
for label,cf,avg,c in [('weak-echo-water',.1,2,1485),('tissue-reference-start',0,1,1540)]:
    s=copy.deepcopy(base)
    s['beamformer'].update(apod=.75,cf=cf,c_m_s=c)
    s['receive'].update(avg_sweeps=avg)
    s['display'].update(debug_view=0,dyn_db=70,curve=1,gain_db=40,auto_gain=False)
    s['note']=('Gentle weak-echo water preset, selected using replay of earlier physical wire captures; '
               'not validated on fresh RF or tissue.' if cf else
               'Unweighted tissue starting reference. NOT validated on tissue. c=1540 is an assumption, '
               'not a measured sound speed. Analog TGC remains the unclipped water value; tissue depth gain is untested. '
               'Single-sweep processing avoids coherent averaging across motion.')
    s['validation']={'status':'replay_only; live checks pending FPGA runtime identity',
                     'study':'docs/weak-echo-study-2026-09-09.md',
                     'sources':[str(ROOT/'bench_runs/wire-21c-1mm'/name/'capture.rf.npz')
                                for name in ['validation-flat-a','validation-flat-b']],
                     'source_runtime_build_id':'8841d2b2 (at original capture, not current runtime)',
                     'quiet_channels_note':base['validation']['quiet_channels_note'],
                     'conditions':'Prior water captures: about 21 C, 1 mm wire near 5 cm, container bottom near 10 cm; unidentified faint scatterer.',
                     'transmit':'Existing +/-40 V supply, unchanged waveform, flat trims. Settings load disarms.',
                     'near_field_limit':'15 us receive delay excludes approximately the first 11 mm of water; this is not shallow-tissue validation.'}
    path=ROOT/'host/presets'/f'{label}.json'
    atomic_json(path,s)
    checked=load_settings(path)
    assert checked['beamformer']['cf']==cf and checked['receive']['avg_sweeps']==avg
    assert not checked['transmit']['armed']

trials=[]
for path in OUT.glob('*/weak-metrics.json'):
    if path.parent.name.startswith('SIMULATION'):continue
    m=json.loads(path.read_text());m['trial']=path.parent.name
    trials.append(m)
paired=[]
for session in ['validation-flat-a','validation-flat-b']:
    for frame in [4,12,20,28]:
        values={name:json.loads((OUT/f'validation-{session}-f{frame}-{name}'/'weak-metrics.json').read_text())
                for name in ['reference','gentle','wire']}
        ref=values['reference']['weak1'];new=values['gentle']['weak1']
        paired.append({'session':session,'frame':frame,
                       'gentle_point_amplitude_fraction':new['peak']/ref['peak'],
                       'gentle_local_background_improvement_db':new['peak_to_local_background_db']-ref['peak_to_local_background_db']})
summary={'status':'replay complete; live acquisition blocked by failed runtime identity check',
         'new_physical_captures':0,'real_rf_reconstructions':len(trials),
         'paired_validation':paired,'trials':trials,
         'limitations':['No tissue phantom or tissue RF','Faint target not proven to be a bubble',
                        'Second weak ROI is not a stable target','Local background is not independently measured electronic noise',
                        'Water cannot establish tissue attenuation, TGC, motion response, or low-contrast lesion detectability']}
atomic_json(OUT/'study-summary.json',summary)

cards=[]
for title,name in [('Wire processing, displayed at 70 dB','validation-validation-flat-b-f20-wire'),
                   ('Unweighted reference, 70 dB','validation-validation-flat-b-f20-reference'),
                   ('Gentle weak echo, 70 dB','validation-validation-flat-b-f20-gentle')]:
    cards.append(f'<figure><figcaption>{title}</figcaption><img src="{name}/image-axes.png"><a href="{name}/settings.json">Full settings</a></figure>')
rows=''.join(f'<tr><td>{html.escape(m["trial"])}</td><td>{m["frame"]}</td><td>{m["weak1"]["peak"]:.3f}</td><td>{m["weak1"]["peak_to_local_background_db"]:.2f}</td><td><a href="{m["trial"]}/image-axes.png">Image</a> · <a href="{m["trial"]}/settings.json">Settings</a></td></tr>' for m in trials)
page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Weak echoes — replay study</title>
<style>body{{background:#0c1117;color:#dce4ed;font:16px system-ui;margin:32px;max-width:1800px}}a{{color:#8bd4ff}}h1{{font-size:30px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}figure{{margin:0}}img{{width:100%}}figcaption{{font-weight:600;margin:12px 0}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #34404a;padding:8px}}.notice{{padding:18px;background:#20313e;line-height:1.5}}p{{max-width:1000px;line-height:1.5}}</style>
<h1>Preserving weak echoes</h1><p class="notice"><b>Replay results, not new physical measurements.</b> {len(trials)} reconstructions from earlier wire-bath RF. The current FPGA did not return the checked runtime identity. Live captures remain pending the programming connection. No tissue has been validated.</p>
<p>The faint target near (+13.5 mm, 53.4 mm) was retained with gentle processing. The second weak region was unstable and was excluded from target validation. Gray background in water may be noise, sidelobes or reverberation; it is not evidence of tissue sensitivity.</p>
<div class="grid">{''.join(cards)}</div>
<p>All three panels use the same original RF frame, 70 dB range, +40 dB gain and linear gray curve. Aperture taper and sweep averaging differ as recorded. These panels deliberately show the tradeoff: more gray also exposes more clutter.</p>
<p><a href="study-summary.json">Complete machine-readable results</a> · <a href="../../docs/weak-echo-study-2026-09-09.md">Interpretation and limits</a></p>
<h2>Separate diffuse-scatterer software check</h2><p>A deterministic 2-D linear-scattering model tests how the actual renderer treats diffuse RF. It does not model the probe or validate tissue performance.</p>
<div class="grid">{''.join(f'<figure><figcaption>SIMULATION — coherence exponent {cf}</figcaption><img src="SIMULATION-diffuse-cf{cf}/image-axes.png"></figure>' for cf in [0,.1,2])}</div>
<h2>Every physical-RF replay trial</h2><table><tr><th>Trial</th><th>Frame</th><th>Faint target peak, raw beamformer units</th><th>Peak/local background, dB</th><th>Artifacts</th></tr>{rows}</table>
<p>Raw peak sums must be normalized before comparing different aperture tapers; the paired validation uses the same taper. Local-background ratios can rise by suppressing everything and were not used alone as the objective.</p></html>'''
(OUT/'report.html').write_text(page,encoding='utf-8')
print(json.dumps({'trials':len(trials),'retention':[min(p['gentle_point_amplitude_fraction'] for p in paired),max(p['gentle_point_amplitude_fraction'] for p in paired)],
                  'local_improvement':[min(p['gentle_local_background_improvement_db'] for p in paired),max(p['gentle_local_background_improvement_db'] for p in paired)]}))
