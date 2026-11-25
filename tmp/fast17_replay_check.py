"""Exercise the stable fast-17 receive path with physical RF in emulated wire order."""
import sys
import copy
from pathlib import Path
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'host'))
from test_rf_debug_ui import HostTests
from bench_render import Renderer
from pulse_methods import BANKS, BankFrame
from acquisition_timing import timing_budget
import rf_debug as files

out=root/'bench_runs/apical-4ch-20261124'
HostTests.setUpClass()
case=HostTests()
case.setUp()
h,w=case.h,case.w
source=files.load_session(root/'host/heart-apical-4chamber.rf.npz')
renderer=Renderer(h)
try:
    assert not h.HW
    cfg=files.load_settings(root/'host/presets/fast17-alternating-24.json')
    w.debug_apply(cfg)
    w.debug_tick()
    h.recorded_tx_reference=source.tx_reference
    cfg=h.settings_snapshot(w)
    budget=timing_budget(cfg,h.pulser,h.cfg['win_words'])
    n=h.cfg['samps']
    tags=((np.arange(n,dtype=np.uint16)%16)<<12)[None,:]
    order=np.array(BANKS[0])
    wire=np.empty((24,1+n//2),dtype=np.uint32)
    elapsed=0
    for i,raw in enumerate(source.rf):
        wire[:,0]=0xe1000000|(order.astype('I')<<16)|((65515+24*i+np.arange(24,dtype='I'))&65535)
        wire[:,1:]=(((raw[order]+2048).astype('H')|tags).view('I'))
        t=time.perf_counter()
        for chunk in np.array_split(wire.ravel(),3):
            h.process(chunk)
        elapsed+=time.perf_counter()-t
    assert len(h.cine.buf)==len(source.rf)
    quality=list(h.cine.quality)
    for i,((_,raw),q) in enumerate(zip(h.cine.buf,quality)):
        assert q['bank']==0 and q['valid'] and q['valid_elements']==list(BANKS[0])
        np.testing.assert_array_equal(raw[list(BANKS[0])],source.rf[i,list(BANKS[0])])
        assert not np.any(raw[list(BANKS[1])])
    # Verify the physical aperture identity survives a selection/save/reopen.
    w.b_freeze.setChecked(True)
    ids=[103,104,105,106]
    frames=[w.review[i][1] for i in ids]
    q=[quality[i] for i in ids]
    archive=out/'fast17-stable-sample.rf.npz'
    files.save_session(archive,frames,np.arange(4)*.01,{'acquired_settings':cfg},q,source.tx_reference)
    w.debug_open_rf(archive,raise_errors=True)
    selected=[]
    comparison=Image.new('RGB',(810,466),'#14212a')
    draw=ImageDraw.Draw(comparison)
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16)
    draw.text((14,9),'Consecutive heart sweeps reconstructed with one stable 24-position aperture',font=font,fill='white')
    for i in range(4):
        raw=w._review_rf(i)
        assert raw.bank==0
        an=h.prepare_analytic(raw,n)
        m,_=renderer.render(an,[-32,32,44,116],256,288)
        selected.append(m)
        if i in (1,2):
            _,image=renderer.render(an,[-40,40,36,116],360,360)
            x=42+(i-1)*397
            draw.text((x,42),f'Stable frame {ids[i]}',font=font,fill='white')
            comparison.paste(Image.fromqimage(image),(x,74))
            for cm in (4,6,8,10):
                y=74+(cm*10-36)*4.5
                draw.text((x-6,y),str(cm),font=font,fill='#c7d7e3',anchor='rm')
    draw.text((42,438),'Depth in cm. Original RF acquisition used sequential element order.',font=font,fill='#c7d7e3')
    comparison.save(out/'fast17-stable-replay.png')
    original=copy.deepcopy(cfg)
    original['transmit']['shot_method']=0
    w.debug_apply(original,replay=True)
    h.recorded_tx_reference=source.tx_reference
    errors=[]
    for i,source_sweep in enumerate(ids):
        excluded=sorted(set(BANKS[1])|{25,46})
        h.set_dead(','.join(map(str,excluded)))
        an=h.prepare_analytic(source.rf[source_sweep],n)
        ref,_=renderer.render(an,[-32,32,44,116],256,288)
        error=float(np.max(np.abs(ref-selected[i]))/np.max(ref))
        assert error < 1e-4
        errors.append(error)
    result=dict(input=source.metadata['rf_sha256'],original_sweeps=len(source.rf),
                frames_verified=len(quality),shots_per_frame=24,samples_per_shot=n,
                zero_padding_and_physical_rows_verified=True,parser_elapsed_seconds=elapsed,
                replay_max_error_relative_to_masked_full_aperture=errors,
                saved_rf_excerpt=str(archive.relative_to(root)),
                timing_model=budget,prior_recording_fps=(len(source.rf)-1)/float(np.ptp(source.timestamps)),
                note='Original sequentially acquired RF was reduced to the fixed live-element group and reordered into emulated USB packets. Host processing time excludes packet generation. Hardware acquisition timing is verified separately in RTL.')
    files.atomic_json(out/'fast17-stable-verification.json',result)
    print(result)
finally:
    source.close()
    renderer.close()
    case.tearDown()
