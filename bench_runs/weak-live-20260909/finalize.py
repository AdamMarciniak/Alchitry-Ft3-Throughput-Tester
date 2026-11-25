"""Summarize the completed physical bench run and save reproducible presets."""
from study import *
from rf_debug import load_settings
import html

def read(name):return json.loads((OUT/name).read_text())

captures=read('rf-summary.json')
trials=[]
derived=[]
for p in sorted(OUT.glob('*/trial.json')):
    t=json.loads(p.read_text()); t['name']=p.parent.name
    if (p.parent/'weak-metrics.json').exists():t['measurements']=json.loads((p.parent/'weak-metrics.json').read_text())
    (derived if p.parent.name.startswith('DERIVED-') else trials).append(t)

display=[]
first=np.load(OUT/'display-70-40/magnitude.npy')
xx,zz=axes(first.shape,BOX)
bottom=(abs(xx)<25)&(zz>70)&(zz<85)
for dyn,gain in [(70,40),(80,30),(90,20),(95,15),(100,10)]:
    mag=np.load(OUT/f'display-{dyn}-{gain}/magnitude.npy')
    assert np.array_equal(mag,first), 'Display changes must not change the linear reconstruction'
    db=20*np.log10(mag/97280+1e-9)
    gray=np.clip((db+gain+dyn)/dyn,0,1)
    display.append({'dyn_db':dyn,'gain_db':gain,'relative_black_threshold_db':-dyn-gain,
                    'bottom_white_fraction':float(np.mean(gray[bottom]>=1)),
                    'all_black_fraction':float(np.mean(gray<=0)),'max_gray':float(gray.max())})

paired=[]
for source in ['validation-1800-a','validation-1600','validation-1800-b']:
    for frame in [8,40,80,112]:
        ref=read(f'{source}-f{frame}-reference/weak-metrics.json')
        new=read(f'{source}-f{frame}-gentle/weak-metrics.json')
        paired.append({'source':source,'frame':frame,
                       'wire_amplitude_retained':new['wire']['peak']/ref['wire']['peak'],
                       'right_feature_amplitude_retained':new['faint_right']['peak']/ref['faint_right']['peak'],
                       'left_feature_amplitude_retained':new['faint_left']['peak']/ref['faint_left']['peak'],
                       'note':'Side features are consistent with wire sidelobes, not verified weak independent targets.'})

summary={'status':'completed physical water-bath acquisition and processing study',
         'physical_captures':len(captures),'physical_sweeps':sum(c['frames'] for c in captures),
         'physical_rf_reconstructions':len(trials),'derived_time_gate_reconstructions':len(derived),
         'runtime_build_id':'8841d2b2','selected_water_capture':'validation-1800-b',
         'selected_water_render':'validation-1800-b-f80-gentle',
         'captures':captures,'display_checks':display,'paired_checks':paired,
         'trials':trials,'derived_trials':derived,
         'limits':['No independent bubble target confirmed','No tissue or tissue phantom acquired',
                   'Water cannot validate tissue attenuation, depth gain or motion performance',
                   'Time-gated RF is a diagnostic derivative and is never the final displayed input']}
atomic_json(OUT/'summary.json',summary)

for label in ['weak-echo-water','tissue-reference-start']:
    p=ROOT/'host/presets'/f'{label}.json'
    old=json.loads(p.read_text())
    archived=OUT/'previous-presets'/p.name
    if not archived.exists():atomic_json(archived,old)
    water=label=='weak-echo-water'
    s=copy.deepcopy(old)
    s['acquisition'].update(tgc_min=1800 if water else 1600,tgc_max=1800 if water else 1600)
    s['beamformer'].update(cf=.05 if water else 0,apod=.75,c_m_s=1485 if water else 1540)
    s['receive'].update(avg_sweeps=2 if water else 1,band_f0_mhz=3.5,band_bw_mhz=3,
                        frequency_compounding=False,matched_filter=False,bg_subtract=False,dejitter_on=False)
    s['display'].update(dyn_db=95,gain_db=15,curve=1,debug_view=0,auto_gain=False)
    s['transmit']['armed']=False
    s['note']=('Fresh water-bath checked weak-echo starting profile. Preserves low gray with mild CF; visible side spots are consistent with wire sidelobes, not confirmed bubbles. Not tissue validated.' if water else
               'Unweighted tissue starting reference, NOT tissue validated. c=1540 is assumed. Single sweep avoids coherent averaging across motion. TGC1600 provides extra headroom compared with the selected water profile; tissue depth gain is untested.')
    s['validation']={'status':'water acquisition and display checked; tissue unvalidated',
                     'study':'docs/weak-echo-live-results-2026-09-09.md',
                     'physical_capture_count':len(captures),'physical_sweep_count':sum(c['frames'] for c in captures),
                     'sources':[str(OUT/name/'capture.rf.npz') for name in ['validation-1800-a','validation-1600','validation-1800-b']],
                     'runtime_build_id':'8841d2b2','water_gain_selection':'1800: no clipping in 320 sweeps; 2000 clipped 7 channels',
                     'conditions':'Water, previously reported around21 C; not remeasured. Wire reconstructed near(-3.2,40.4)mm, strong bottom near75mm. No independent bubble target established.',
                     'quiet_channels_note':'The existing 10-channel reconstruction mask is retained; all48 acquired. This is not a diagnosis of broken elements.',
                     'transmit':'Existing +/-40 V supply and waveform unchanged; flat trims, 15us receive delay,300us gap.',
                     'display':'95dB/+15dB retains the same -110dB relative black threshold as70dB/+40dB; display-only, not receiver dynamic range.',
                     'host_requirement':'TFM GL host with display range extended to100dB; settings loading remains disarmed.'}
    atomic_json(p,s)
    checked=load_settings(p)
    assert checked['display']['dyn_db']==95 and not checked['transmit']['armed']

cards=[]
for title,name in [('Previous wire processing','final-wire'),('Unweighted reference','validation-1800-b-f80-reference'),('Selected gentle water profile','validation-1800-b-f80-gentle')]:
    cards.append(f'<figure><figcaption>{title}</figcaption><a href="{name}/image-axes.png"><img src="{name}/image-axes.png"></a><a href="{name}/settings.json">Settings</a></figure>')
caprows=''.join(f'<tr><td><a href="{c["capture"]}/capture.rf.npz">{c["capture"]}</a></td><td>{c["tgc"]}</td><td>{c["frames"]}</td><td>{c["valid_frames"]}</td><td>{c["max_adc_counts"]:.0f}</td><td>{"Rejected: clipping on "+str(c["clipped_channels"]) if c["clipped_channels"] else "No clipping"}</td></tr>' for c in captures)
trialrows=''.join(f'<tr><td>{html.escape(t["name"])}</td><td>{t["frame"]}</td><td><a href="{t["name"]}/image-axes.png">Image</a> · <a href="{t["name"]}/settings.json">Settings</a> · <a href="{t["name"]}/magnitude.npy">Linear magnitude</a></td></tr>' for t in trials)
page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Fresh weak-echo bench results</title>
<style>body{{background:#0b1117;color:#dee7ee;font:16px system-ui;margin:32px;max-width:1750px}}a{{color:#88d3ff}}p{{max-width:1050px;line-height:1.55}}.note{{background:#1c303b;padding:18px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}figure{{margin:0}}img{{width:100%}}figcaption{{font-weight:600;margin:12px 0}}td,th{{text-align:left;padding:9px;border-bottom:1px solid #31414d}}table{{border-collapse:collapse;width:100%}}</style>
<h1>Fresh weak-echo water-bath results</h1><p class="note"><b>{len(captures)} physical captures · {sum(c['frames'] for c in captures)} complete sweeps · {len(trials)} reconstructions.</b> The FPGA runtime identity was verified before every capture. Selected gain1800 stayed unclipped in all320 sweeps tested at that gain. Gain2000 clipped7channels and was rejected.</p>
<p>The selected profile preserves gray and avoids a solid-white bottom band. It exposes more noise and clutter than the wire preset. This bath supplied no independently verified bubble target; it does not establish tissue performance.</p>
<div class="grid">{''.join(cards)}</div>
<p>All panels come from frame80 of the same final physical recording. Wire: CF2,4sweeps,45dB/+40dB,Hann. Reference: CF0,1sweep,95dB/+15dB,75%taper. Gentle: CF0.05,2sweeps,95dB/+15dB,75%taper. These are different intended uses, not a claim that the cleanest background is best.</p>
<h2>Display-only comparison</h2><p>Both images below use exactly identical linear magnitude. Lowering gain while widening the display window preserves the same -110dB black threshold and recovers highlight gradation.</p>
<div class="grid"><figure><figcaption>70dB, +40dB: bottom saturates on screen</figcaption><img src="display-70-40/image-axes.png"></figure><figure><figcaption>95dB, +15dB: highlights retained</figcaption><img src="display-95-15/image-axes.png"></figure></div>
<h2>Why the side spots are not bubble targets</h2><p>A diagnostic derivative retaining only the predicted wire-echo time window reproduces most of both side spots. Removing that window largely removes them. This is strong evidence for wire-related sidelobes; neither derived file is used for the final profile.</p>
<div class="grid"><figure><figcaption>Original RF</figcaption><img src="gain-1800-avg1/image-axes.png"></figure><figure><figcaption>DERIVED: wire echo window only</figcaption><img src="DERIVED-wire-window-2us/image-axes.png"></figure><figure><figcaption>DERIVED: wire echo window removed</figcaption><img src="DERIVED-wire-excluded-2us/image-axes.png"></figure></div>
<h2>Physical RF and integrity</h2><table><tr><th>Capture/RF</th><th>TGC</th><th>Sweeps</th><th>Complete</th><th>ADC peak</th><th>Selection check</th></tr>{caprows}</table>
<p><a href="summary.json">All results and trial definitions</a> · <a href="rf-summary.json">RF checks and hashes</a> · <a href="../../docs/weak-echo-live-results-2026-09-09.md">Interpretation and final presets</a></p>
<h2>Every reconstruction</h2><table><tr><th>Trial</th><th>Frame</th><th>Artifacts</th></tr>{trialrows}</table></html>'''
(OUT/'report.html').write_text(page,encoding='utf-8')
print(json.dumps({'captures':len(captures),'sweeps':sum(c['frames'] for c in captures),'renders':len(trials),'derived_renders':len(derived),'display':display},indent=2))
