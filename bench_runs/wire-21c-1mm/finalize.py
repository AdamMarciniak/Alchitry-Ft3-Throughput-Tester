"""Produce the reviewable result and portable presets from measured trials."""
import copy
import html
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'host'))
from rf_debug import atomic_json, load_session, validate_settings, FIELDS, BOOLS

frames=[4,12,20,28]
rows=[]
for session in ['validation-air-control','validation-flat-a','validation-flat-b']:
    for view in ['das','weighted']:
        values=[json.loads((OUT/f'{session}-{view}-{i}'/'metrics.json').read_text()) for i in frames]
        row={'session':session,'view':view,'frames':frames}
        for key in ['normalized_peak','wide_arc_p99_db','wide_arc_max_db','lateral_width_6db_mm']:
            v=[r[key] for r in values]
            row[key]={'min':min(v),'max':max(v),'mean':float(np.mean(v))}
        rows.append(row)

captures=[]
for p in sorted(OUT.glob('*/capture.rf.npz')):
    r=json.loads((p.parent/'capture.report.json').read_text())
    result=json.loads((p.parent/'result.json').read_text())
    captures.append({'name':p.parent.name,'frames':r['frames_total'],
                     'valid_frames':r['frames_total']-r['degraded_frames_total'],
                     'max_element_clipping_fraction':max(e['clipped_fraction'] for e in r['elements']),
                     'accepted':result['accepted'],'rf':str(p)})

s=load_session(OUT/'validation-flat-b/capture.rf.npz')
try:
    full=copy.deepcopy(s.metadata['review_settings'])
    for section in ['acquisition','transmit']:
        full[section]=copy.deepcopy(s.metadata['acquired_settings'][section])
    validate_settings(full)
    preset={'settings_schema':1,'note':'WIRE PHANTOM ONLY: 21 C bath, 1 mm wire near 5 cm. Strong coherence weighting suppresses diffuse tissue. Validated with flat trims, c=1485 m/s and 15 us receive start. Loading never arms transmission.'}
    for section,fields in FIELDS.items():
        names=list(fields)+BOOLS.get(section,[])
        preset[section]={k:full[section][k] for k in names if k in full[section]}
    preset['transmit'].update(armed=False,single_elem=None,trim_ns=[0.]*48)
    preset['beamformer']['dead']=[2,3,6,7,18,19,22,23,25,46]
    preset['display'].update(debug_view=0,dyn_db=45,gain_db=40,curve=1,auto_gain=False,zoom=1,pan_cx=0,pan_cz=.06)
    preset['validation']={'rf':str(OUT/'validation-flat-b/capture.rf.npz'),
                          'fpga_runtime_build_id':s.metadata['firmware_readback_before_arm']['runtime_build_id'],
                          'firmware_build_dir':s.metadata['programming_receipt']['build_dir'],
                          'quiet_channels_note':'Negligible wire AND bottom echoes in these captures; not a diagnosis of physically broken elements.',
                          'hardware_supply':'Existing +/-40 V, not electronically measured'}
finally:
    s.close()

validate_settings(preset)
presets=ROOT/'host/presets'
presets.mkdir(exist_ok=True)
atomic_json(presets/'wire-21c-1mm-best.json',preset)
diagnostic=copy.deepcopy(preset)
diagnostic['beamformer']['cf']=0
diagnostic['display'].update(debug_view=1,dyn_db=80)
diagnostic['note']='Ordinary DAS reference for the same wire acquisition. Preserves diffuse returns for comparison. This water/phantom acquisition profile is not a cardiac preset.'
atomic_json(presets/'wire-21c-1mm-das.json',diagnostic)

air=rows[0]
flat=next(r for r in rows if r['session']=='validation-flat-b' and r['view']=='das')
weighted=next(r for r in rows if r['session']=='validation-flat-b' and r['view']=='weighted')
gain_db=float(20*np.log10(flat['normalized_peak']['mean']/air['normalized_peak']['mean']))
retained=weighted['normalized_peak']['mean']/flat['normalized_peak']['mean']
summary={'scope':'Best of the tested settings for this stationary 1 mm wire in approximately 21 C water; not a global optimum or tissue-imaging validation.',
         'captures':captures,'validation':rows,'flat_trim_das_signal_gain_db':gain_db,
         'final_coherence_peak_retention':retained,
         'candidate':'flat trims; quiet-channel mask; TGC 1600 constant; receive delay 15 us; gap 300 us; 2-5 MHz receive band; Hann aperture; CF exponent 2; 4-sweep average; 45 dB display; +40 dB display gain',
         'residual':'A small point-like off-wire feature remains near x=+13.6 mm, z=53.3 mm. It may be a bubble or another reflector; this has not been identified physically. Container-bottom responses remain visible.',
         'reference_for_water_model':'https://resource.npl.co.uk/acoustics/techguides/soundpurewater/underlying-phys.html',
         'presets':[str(presets/'wire-21c-1mm-best.json'),str(presets/'wire-21c-1mm-das.json')]}
atomic_json(OUT/'study-summary.json',summary)

tr=[]
for row in rows:
    fmt=lambda key: f"{row[key]['min']:.1f} to {row[key]['max']:.1f}"
    tr.append(f"<tr><td>{row['session']}</td><td>{row['view']}</td><td>{fmt('wide_arc_p99_db')}</td><td>{fmt('wide_arc_max_db')}</td><td>{row['normalized_peak']['mean']:.6f}</td></tr>")
capture_rows=''.join(f"<tr><td>{r['name']}</td><td>{r['valid_frames']}/{r['frames']}</td><td>{100*r['max_element_clipping_fraction']:.3f}%</td><td><a href='{r['name']}/capture.rf.npz'>RF</a></td></tr>" for r in captures)
figures=[('Wire close-up, chosen preset','final-wire-closeup/image-axes.png'),
         ('Whole scene, chosen preset','validation-flat-b-weighted-20/image-axes.png'),
         ('Air trims: ordinary DAS, same gain and display','validation-air-control-das-20/image-axes.png'),
         ('Flat trims: ordinary DAS, same gain and display','validation-flat-b-das-20/image-axes.png')]
imgs=''.join(f"<figure><figcaption>{html.escape(label)}</figcaption><a href='{src}'><img src='{src}'></a></figure>" for label,src in figures)
page=f'''<!doctype html><meta charset="utf-8"><title>Measured wire bench result</title>
<style>body{{font:16px/1.55 system-ui;background:#101418;color:#e1e7ee;max-width:1240px;margin:32px auto;padding:0 24px}}h1,h2{{line-height:1.2}}a{{color:#93ccff}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}figure{{margin:0}}img{{width:100%}}figcaption{{padding:12px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #344}}.note{{background:#1c2834;padding:18px}}code{{color:#c8dfef}}@media(max-width:700px){{.images{{grid-template-columns:1fr}}}}</style>
<h1>Wire bench: arcs suppressed, result repeated</h1>
<p>Physical CH6-2 captures: approximately 21 °C water, 1 mm wire near 5 cm, container bottom visible deeper. {len(captures)} RF acquisitions in this study, followed by processing sweeps and a flat/air/flat confirmation.</p>
<div class="note">The chosen wire display suppresses most measured arc-region energy while retaining about {100*retained:.0f}% of the ordinary-DAS wire peak on the same RF. It uses strong coherence weighting and is <strong>not a preset for recovering subtle tissue gray</strong>.</div>
<div class="images">{imgs}</div>
<h2>Changes supported by the measurements</h2>
<ul><li>Gap 50→300 µs: the first 32 saved sweeps were incomplete; all subsequent acquisition conditions passed. The original stream had continuous frame counters but skipped element IDs.</li>
<li>Air-derived→flat trims: ordinary-DAS wire peak increased by {gain_db:.1f} dB, with the same gain, band, channel mask and aperture. Broad arc-region p99 dropped from about −12 to −21 dB relative to the wire. This repeated after restoring air trims and returning to flat.</li>
<li>Constant TGC 1600 and receive start 15 µs: no clipping in the final recordings, including the deeper bottom response. The receive start excludes ranges shallower than approximately 11 mm.</li>
<li>Quiet channel IDs excluded in reconstruction: 2, 3, 6, 7, 18, 19, 22, 23, 25, 46. They had negligible band-limited echo at both the wire and bottom in these recordings. All 48 IDs are still acquired. Their physical fault status is undetermined.</li>
<li>2–5 MHz band, Hann aperture, coherence exponent 2, four-frame averaging, fixed 45 dB display range and +40 dB display gain produced the chosen wire image. Narrower bands, other aperture weights, matched filtering, frequency compounding, stronger coherence and other gains/delays were compared. Further suppression beyond CF=2 reduced the wire peak with little visible benefit.</li></ul>
<h2>Fresh A/B/A validation</h2>
<p>Each condition contains 32 complete frames with zero clipped samples. Four other frames per recording were measured with identical processing. “Wide arc” covers a ±4 mm shell around the wire's range from the measured array's curvature centre, over the full ±50 mm image width, excluding ±5 mm laterally around the target. These are image-domain relative amplitude measurements, not acoustic power or independent SNR measurements.</p>
<table><tr><th>Acquisition</th><th>View</th><th>Arc p99 / wire (dB)</th><th>Strongest off-wire feature (dB)</th><th>Mean normalized wire peak</th></tr>{''.join(tr)}</table>
<p>The remaining strongest feature is point-like near (+13.6, 53.3) mm and may be a bubble or another reflector. It was retained. The bottom is a real, strong reflector and still appears in the whole-scene view. Finite-wire width after nonlinear coherence weighting is not a resolution measurement; no claim of submillimetre resolving power is made.</p>
<h2>Saved settings and RF</h2>
<p><a href="../../host/presets/wire-21c-1mm-best.json">Chosen wire preset</a> · <a href="../../host/presets/wire-21c-1mm-das.json">Ordinary-DAS reference preset</a> · <a href="validation-flat-b/capture.rf.npz">Final 32-frame RF</a> · <a href="study-summary.json">Machine-readable results</a></p>
<p>Load a preset with the host's <strong>load settings…</strong> button, or use <code>python tools/bench.py configure host/presets/wire-21c-1mm-best.json</code> with a running bench host. Loading leaves transmission off. The uploaded firmware is temporary RAM build <code>8841d2b2</code>; its disarmed identity/configuration response was checked before every capture.</p>
<details><summary>All physical captures and clipping checks</summary><table><tr><th>Condition</th><th>Valid frames</th><th>Worst channel clipping</th><th>Recording</th></tr>{capture_rows}</table></details>
<p>Water sound speed was modeled as approximately 1485 m/s for the reported temperature, using the <a href="https://resource.npl.co.uk/acoustics/techguides/soundpurewater/underlying-phys.html">NPL water sound-speed reference</a>. Temperature and supply voltage were owner-reported, not read back electronically.</p>'''
(OUT/'report.html').write_text(page,encoding='utf-8')
print(json.dumps({'captures':len(captures),'flat_gain_db':gain_db,'cf_peak_retention':retained,'report':str(OUT/'report.html'),'presets':summary['presets']},indent=2))
