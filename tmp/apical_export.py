from apical_review import (h,w,ren,files,root,s,src,out,orig,alive,halves,metrics,setup,
                           n,caliper,close,Image,ImageDraw,ImageFont,np,gaussian_filter,corr)
import copy
import subprocess
import shutil

chosen=dict(**caliper,lo=1.5,hi=5.1,cf=.45)
validation=[5,19,37,53,68,84,101,119,138,155,177,197]
viewbox=[-56,56,22,154]
width,height=448,528
font=lambda size:ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',size)
small,normal=font(15),font(20)

def select(opt):
    setup(opt)
    if opt:
        h.state.update(gain=40,dyn=78,curve=.95)

def checks():
    results={}
    for name,opt in [('recorded',{}),('selected',chosen),('selected with original geometry',
                    {k:v for k,v in chosen.items() if k not in ('radius','pitch')}),
                    ('coherence off',dict(chosen,cf=0)),('frequency compounding',dict(chosen,comp=True))]:
        select(opt)
        values=[]; shape=[]; contrast=[]
        for index in validation:
            an=h.prepare_analytic(s.rf[index],n)
            values.append(metrics(an))
            m,_=ren.render(an,[-20,20,45,105],400,600)
            x=np.arange(400)*.1-19.95; z=np.arange(600)*.1+45.05
            rows=(z>=53)&(z<=72)
            center=m[np.ix_(rows,abs(x)<5)]
            sides=m[np.ix_(rows,(abs(x)>11)&(abs(x)<18))]
            contrast.append(float(20*np.log10(np.median(sides)/np.median(center))))
            log=20*np.log10(np.maximum(m[:,abs(x)<12],1e-7))
            log-=gaussian_filter(log,(20,40))
            lens=[]
            for a in (log,log.T):
                prev=1.
                for lag in range(1,45):
                    v=corr(a[lag:],a[:-lag])
                    if v<.5:
                        lens.append(.1*(lag-1+(prev-.5)/(prev-v)))
                        break
                    prev=v
            shape.append(lens)
        results[name]=dict(split_correlations=np.median(values,axis=0).round(3).tolist(),
                side_to_center_contrast_db=round(float(np.median(contrast)),2),
                texture_half_correlation_lag_axial_lateral_mm=np.median(shape,axis=0).round(3).tolist())
    r=dict(validation_frames=validation,source=src.name,rf_sha256=s.metadata['rf_sha256'],
           depth_bands_mm=[[45,70],[70,105],[105,135],[135,150]],
           metrics='Independent 23-element groups from comparison-metrics.json. Median Pearson correlations across frames for fine and coarse log-envelope texture. Coherent artifacts can agree. Separate side-to-center contrast is median-amplitude ratio at 53-72 mm, |x| 11-18 mm versus |x| <5 mm. Texture lags describe grayscale structure in log amplitude, not target resolution.',
           calipers=dict(chord_mm=62.2,rise_mm=8.5,outer_radius_mm=61.1447,outer_arc_mm=65.2527,
                         pitch_assuming_192_full_face_cells_mm=.339858),
           candidates=results)
    files.atomic_json(out/'validation.json',r)
    print('validation',results,flush=True)

def replay_file():
    select(chosen)
    rev=copy.deepcopy(orig)
    rev['receive'].update(band_f0_mhz=3.3,band_bw_mhz=3.6,band_lo_mhz=1.5,band_hi_mhz=5.1)
    rev['beamformer'].update(R_mm=61.1,pitch_mm=.340,aperture_mm=round(.340*47,3),cf=.45)
    rev['display'].update(gain_db=40,dyn_db=78,curve=.95)
    rev['source']='file replay'
    rev['note']='Four-second apical recording. Review using the user-measured outer face geometry.'
    w.debug_apply(rev,replay=True);h.recorded_tx_reference=s.tx_reference
    rev['summary']=w.info_line().split('  [SIM]')[0]+'  [recorded RF replay]'
    rev['transmit']['armed']=False
    meta=copy.deepcopy(s.metadata)
    meta.update(review_settings=rev,parent_recording_file=src.name)
    path=out/'heart-apical-reviewed.rf.npz'
    files.save_session(path,s.rf,s.timestamps,meta,s.quality,s.tx_reference,s.background)
    w.debug_open_rf(path,raise_errors=True)
    loaded=w.debug_session
    assert loaded.metadata['rf_sha256']==s.metadata['rf_sha256']
    assert loaded.quality==s.quality and loaded.metadata['acquired_settings']==s.metadata['acquired_settings']
    assert np.array_equal(loaded.timestamps,s.timestamps) and np.array_equal(loaded.tx_reference,s.tx_reference)
    assert np.isclose(h.state['band_f0'],3.3) and np.isclose(h.state['cf'],.45)
    assert h.geom['R_mm']==61.1 and np.isclose(h.geom['pitch_mm'],.34)
    print('Verified host file replay, 208 original sweeps',flush=True)

def canvas():
    page=Image.new('RGB',(1016,636),'#12202b')
    d=ImageDraw.Draw(page)
    for x,label in [(64,'Recorded settings'),(544,'Reviewed settings')]:
        d.text((x,11),label,font=normal,fill='#f3f7fa')
        for cm in [4,6,8,10,12,14]:
            y=54+(cm*10-viewbox[2])*4
            d.line((x-4,y,x-1,y),fill='#afc2ce')
            if x==64: d.text((x-9,y),str(cm),anchor='rm',font=small,fill='#d0dce5')
        for mm in [-40,-20,0,20,40]:
            xx=x+(mm+56)*4
            d.line((xx,583,xx,587),fill='#afc2ce')
            d.text((xx,589),str(mm),anchor='mt',font=small,fill='#d0dce5')
    d.text((7,49),'cm',font=small,fill='#d0dce5')
    d.text((64,610),'Lateral position (mm)',font=small,fill='#d0dce5')
    return page

def media():
    # Map host arrival times to 1 ms ticks. Preserve all sweeps and the uneven
    # frame intervals with variable-duration presentation timestamps.
    import tempfile
    from pathlib import Path
    elapsed=s.timestamps-s.timestamps[0]
    ticks=np.rint(elapsed*1000).astype(int)
    for i in range(1,len(ticks)):
        ticks[i]=max(ticks[i],ticks[i-1]+1)
    with tempfile.TemporaryDirectory(dir=root/'tmp',prefix='apical-cine-') as work:
        path=Path(work)
        # All original images are loaded for the comparison. The second pass
        # panel uses the same index, Cartesian view, pixel spacing and timestamp.
        select({})
        original=[]
        for rf in s.rf:
            _,im=ren.render(h.prepare_analytic(rf,n),viewbox,width,height)
            original.append(Image.fromqimage(im).convert('L'))
        select(chosen)
        base=canvas()
        for i,rf in enumerate(s.rf):
            _,im=ren.render(h.prepare_analytic(rf,n),viewbox,width,height)
            image=base.copy()
            image.paste(original[i],(64,54))
            image.paste(Image.fromqimage(im),(544,54))
            d=ImageDraw.Draw(image)
            d.text((993,618),f'{elapsed[i]:.2f} s    Frame {i+1} / {len(s.rf)}',anchor='rm',font=small,fill='#d0dce5')
            if i==104: image.save(out/'comparison.png')
            image.save(path/f'{i:03}.png',compress_level=1)
        terms=[f'{tick}*eq(N,{i})' for i,tick in enumerate(ticks)]
        while len(terms)>1:
            terms=['('+'+'.join(terms[i:i+2])+')' for i in range(0,len(terms),2)]
        (path/'times.filter').write_text(f"settb=1/1000,setpts='{terms[0]}'",encoding='ascii')
        subprocess.run([shutil.which('ffmpeg'),'-loglevel','error','-nostdin','-y','-framerate','50',
                        '-i','%03d.png','-filter_script:v','times.filter','-an','-c:v','libx264','-crf','16','-preset','fast',
                        '-pix_fmt','yuv420p','-vsync','vfr','-enc_time_base','1:1000',
                        '-movflags','+faststart',str(out/'comparison.mp4')],cwd=path,check=True)
    print('Exported comparison cine',flush=True)

if __name__=='__main__':
    try:
        checks()
        replay_file()
        media()
    finally: close()
