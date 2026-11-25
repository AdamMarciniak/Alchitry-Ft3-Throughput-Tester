from phantom_compare import *
from PIL import Image, ImageDraw, ImageFont
out=root/'bench_runs/phantom-pulse-comparison'
rows={}
anchor=None
imgs=[]
for name in ['current','final-live']:
    s=files.load_session(out/(name+'.rf.npz'))
    cfg=copy.deepcopy(s.metadata['acquired_settings'])
    w.debug_apply(cfg,replay=True);h.recorded_tx_reference=s.tx_reference
    raw=s.rf[:]
    rows[name]={}
    for start in [0,16,32]:
        m=metrics(raw[start:start+16],cfg,None,name,'',anchor)
        if anchor is None: anchor=m['peak_position_mm']
        rows[name][str(start)]=m
    w.debug_apply(cfg,replay=True);h.recorded_tx_reference=s.tx_reference
    # Keep a shared display transfer and averaging for the comparison figure.
    h.state.update(cf=.25,dyn=66,gain=35,curve=.85,auto=False,debug_view=0)
    mag,im=ren.render(h.prepare_analytic(raw[:8].mean(0),h.cfg['samps']),box,W,H)
    if name=='final-live': annotated(im,out/'wire-and-phantom.png','Broad 2–6 MHz chirp   |   Wire and psyllium gelatin')
    imgs.append(Image.fromqimage(im))
    rows[name]['total_valid']=sum(q['valid'] for q in s.quality)
    rows[name]['shape']=list(s.rf.shape)
    rows[name]['identity']=s.metadata['firmware_readback_before_arm']['runtime_build_id']
    print(name,[(round(m['lateral_width_6db_mm'],2),round(m['axial_width_6db_mm'],2),round(m['contrast_db'],1),np.round(m['grain_mm'],2),round(m['background_repeat'],4),m['clip_wire_gel_fraction']) for k,m in rows[name].items() if k.isdigit()])
    s.close()
files.atomic_json(out/'confirmation.json',dict(regions_mm=dict(texture_lateral=[-5.5,5.5],texture_depth=[29,37],wire_search_anchor=anchor),records=rows))
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16)
big=ImageFont.truetype('C:/Windows/Fonts/seguisb.ttf',20)
# Crop to the same central 18 mm of the aperture in both views and include the base.
panels=[im.crop((104,26,338,520)).resize((351,741)) for im in imgs]
fig=Image.new('RGB',(810,840),'#111820');d=ImageDraw.Draw(fig)
for i,(title,img) in enumerate(zip(['Original chirp','Broad chirp, tuned receive'],panels)):
    x0=52+397*i;y0=48
    d.text((x0,y0-36),title,font=big,fill='white')
    fig.paste(img,(x0,y0))
    for mm in range(10,46,5):
        y=y0+round(((mm-8)*13-26)*1.5)
        d.line((x0-5,y,x0,y),fill='#d7dce2')
        d.text((x0-9,y),str(mm),font=font,anchor='rm',fill='#e2e9f0')
    target=rows[['current','final-live'][i]]['0']['peak_position_mm']
    tx=x0+round(((target[0]-box[0])*13-104)*1.5)
    ty=y0+round(((target[1]-8)*13-26)*1.5)
    d.line((tx+12,ty-7,tx+42,ty-25),fill='#ffca77',width=2)
    d.text((tx+45,ty-27),'Wire',anchor='lm',font=font,fill='#ffca77')
    for mm in [-5,0,5]:
        xp=x0+round(((mm-box[0])*13-104)*1.5)
        d.line((xp,y0+741,xp,y0+746),fill='#e2e9f0')
        d.text((xp,y0+748),str(mm),anchor='mt',font=font,fill='#e2e9f0')
d.text((405,825),'Lateral position and depth in mm',anchor='mm',font=font,fill='#dce7ed')
fig.save(out/'before-after.png')
h.stats['alive']=False;ren.close();w.close()
