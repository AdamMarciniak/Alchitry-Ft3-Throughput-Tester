"""Offline test of acquisition timing and reduced-aperture reconstructions."""
from apical_review import h, w, ren, files, root, src, out, s, n, close, setup, mask, caliper
from acquisition_timing import fast12_settings, timing_budget
from bench_render import wire_metrics
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter
import numpy as np

review=dict(**caliper,lo=1.5,hi=5.1,cf=.45)
dead={25,46}
full=np.arange(48)
center=full[12:36]
# Break periodic spacing while retaining two complementary 24-shot lists.
# Both banks include a dead channel so each has 23 good measurements.
pairs=full.reshape(24,2)
which=np.random.default_rng(179).integers(0,2,24)
which[12]=1
which[23]=1
spread=pairs[np.arange(24),which]
complement=pairs[np.arange(24),1-which]
configs={'All 48':full,'Middle 24':center,'Distributed 24 A':spread,'Distributed 24 B':complement}
small=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',15)
large=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',20)

def use(elements):
    mask([int(i) for i in elements if i not in dead])

def ideal(target=(0.,80.)):
    pos=h.elem_uniform()[:,:2].astype('d')*1000
    delay=np.linalg.norm(pos-np.array(target),axis=1)*2000/h.state['c']
    t=np.arange(n)*1e6/h.FS_HZ + h.state['dly_us'] - h.state['t0_ns']*.001
    dt=t[None,:]-delay[:,None]
    iq=np.exp(-.5*(dt/.19)**2+2j*np.pi*3.3*dt)
    return np.stack([iq.real,iq.imag],axis=-1).astype('f')

def point_metrics(phantom):
    box=[-30,30,76,84]
    mag,_=ren.render(phantom,box,1200,160)
    met=wire_metrics(mag,box,[-1,1,79,81])
    x=box[0]+(np.arange(1200)+.5)*.05
    side=mag[:,abs(x)>=7].max()
    return dict(lateral_half_amplitude_width_mm=met['lateral_width_6db_mm'],
                outer_peak_relative_db=float(20*np.log10(side/met['peak'])),
                point_peak=met['peak'])

def evaluate():
    original=s.metadata['acquired_settings']
    frames=len(s.rf)
    elapsed=float(s.timestamps[-1]-s.timestamps[0])
    fcnt=np.array([i for q in s.quality for i in q['element_frame_counters']])
    assert np.all((np.diff(fcnt)&65535)==1)
    reports={}
    for name,cfg in [('recorded',original),('12 cm fast',fast12_settings(original))]:
        w.debug_apply(cfg,replay=True)
        reports[name]=timing_budget(cfg,h.pulser,h.cfg['win_words'])
    w.debug_apply(original,replay=True)
    h.recorded_tx_reference=s.tx_reference
    setup(review)
    h.state.update(gain=40,dyn=78,curve=.95)
    target=ideal()
    results={}
    for name,elems in configs.items():
        use(elems);results[name]=dict(elements=elems.tolist(),good_channels=h.n_alive(),**point_metrics(target))
    # Compare spatial grain at identical physical coordinates over 12 sweeps.
    # It describes texture only. With fewer channels, different scatterers and
    # sidelobes can all change the observed grain.
    box=[-10,10,52,104]
    examples=[5,19,37,53,68,84,101,119,138,155,177,197]
    for name,elems in configs.items():
        use(elems)
        lags=[]
        for index in examples:
            rf=h.prepare_analytic(s.rf[index],n)
            m,_=ren.render(rf,box,200,520)
            v=20*np.log10(np.maximum(m,1e-6)); v-=gaussian_filter(v,(20,40))
            row=[]
            for a in (v,v.T):
                prev=1.
                for lag in range(1,60):
                    lft=a[:-lag].flatten();rgt=a[lag:].flatten()
                    lft-=lft.mean();rgt-=rgt.mean()
                    value=float(np.dot(lft,rgt)/np.sqrt(np.dot(lft,lft)*np.dot(rgt,rgt)))
                    if value<=.5:
                        row.append(.1*(lag-1+(prev-.5)/(prev-value))); break
                    prev=value
            lags.append(row)
        results[name]['observed_texture_half_correlation_axial_lateral_mm']=np.median(lags,axis=0).round(3).tolist()
    # Match brightness using the simulated on-axis point gain. There is one
    # scalar per configuration, with no histogram equalization or per-frame gain.
    use(full); fullscale=h.full_scale(h.state['apod'])
    refs=results['All 48']['point_peak']
    rf=h.prepare_analytic(s.rf[104],n)
    page=Image.new('RGB',(1110,548),'#15212c'); d=ImageDraw.Draw(page)
    d.text((24,12),'Same recorded sweep, three receive apertures',font=large,fill='white')
    for j,(name,elems) in enumerate(list(configs.items())[:3]):
        use(elems)
        box=[-34,34,35,113]
        m,_=ren.render(rf,box,340,390)
        mag=m*refs/results[name]['point_peak']
        db=20*np.log10(np.maximum(mag/fullscale,1e-9))
        v=np.uint8(255*h.scurve_np(np.clip((db+40+78)/78,0,1),.95))
        xp=41+355*j; yp=95
        page.paste(Image.fromarray(v),(xp,yp))
        d.text((xp,57),name,font=large,fill='white')
        if j==0:
            for cm in range(4,12):
                d.text((xp-5,yp+(10*cm-35)*5),str(cm),font=small,anchor='rm',fill='#c7d6df')
            d.text((4,83),'cm',font=small,fill='#c7d6df')
        d.text((xp,494),f"Point-model width at 8 cm: {results[name]['lateral_half_amplitude_width_mm']:.2f} mm",font=small,fill='#c7d6df')
    page.save(out/'acquisition-apertures.png')
    fps=(frames-1)/elapsed
    outdata=dict(frame_count=frames,elapsed_seconds=elapsed,complete=sum(q['valid'] for q in s.quality),
        host_arrival_mean_fps=fps,host_mean_frame_interval_ms=1000/fps,consecutive_shot_counters=len(fcnt),
        provenance=s.metadata['timestamp_basis'],timing_model=reports,apertures=results,example_frame=104,
        measured_texture_frames=examples,point_model='Isolated stationary point, 80 mm on axis, 3.3 MHz analytic Gaussian pulse, 0.19 us sigma; reviewed beamformer and dead mask. Width at -6 dB amplitude. Side peak searched at 7-30 mm lateral in 76-84 mm depth.',
        timing_limit='The middle subset spans 24 consecutive original firings. Distributed subsets span almost the full original sweep. Only a new sequence could acquire them in half the time.')
    files.atomic_json(out/'acquisition-timing.json',outdata)
    print(reports, fps)
    for name,r in results.items(): print(name,r['lateral_half_amplitude_width_mm'],r['outer_peak_relative_db'],r['observed_texture_half_correlation_axial_lateral_mm'])

if __name__=='__main__':
    try: evaluate()
    finally: close()
