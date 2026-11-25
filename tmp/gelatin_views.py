from gelatin_analysis import *
s,cfg=load('flat-gain')
h.state.update(apod=.2,accept=25,mf=True,band_f0=3.5,band_bw=5,debug_view=0,auto=False,curve=.85)
raw=s.rf[:8].mean(0)
for cf in [.15,.35,.55]:
    for comp in [False,True]:
        h.state.update(cf=cf,freq_comp=comp)
        m,_=render(raw)
        p=wire_metrics(m,box,search)['peak']
        # Map the wire near 88% on an absolute, fixed display.
        dyn=54; gain=min(40,round(-20*np.log10(p/h.full_scale(.2))-dyn*.12))
        h.state.update(gain=gain,dyn=dyn)
        m,im=render(raw)
        print(cf,comp,gain,measure(m),'bg median level',np.median(array(im)[roi]),flush=True)
        annotated(im,out/f'view-{cf}-{int(comp)}.png',f'Coherence {cf:.2f}   |   '+('Three bands' if comp else 'Single band'))
h.stats['alive']=False;ren.close();w.close()
