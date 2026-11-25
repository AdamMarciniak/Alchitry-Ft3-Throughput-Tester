import numpy as np, sys, os, copy, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'bench_runs/gelatin-20261124'
sys.path.insert(0,str(root/'host'))
sys.argv=['tfm_gl_host.py','sim']
os.environ['QT_QPA_PLATFORM']='offscreen'
import tfm_gl_host as h, rf_debug as files
from bench_render import Renderer,wire_metrics
from PIL import Image,ImageDraw,ImageFont
app=h.QApplication(sys.argv)
w=h.Main()
ren=Renderer(h)
box=[-17,17,8,52]
W,H=442,572
x=box[0]+(np.arange(W)+.5)*34/W
z=box[2]+(np.arange(H)+.5)*44/H
roi=(abs(x[None,:])<6)&(z[:,None]>23)&(z[:,None]<36)
search=[-8,5,17.5,20.7]
def render(raw):
    an=h.prepare_analytic(raw,raw.shape[1])
    return ren.render(an,box,W,H)
def cvt(im):
    return im.toImage() if hasattr(im,'toImage') else im
def array(im):
    return np.asarray(im.toPython() if hasattr(im,'toPython') else Image.fromqimage(im))[:,:,0]
def measure(m):
    met=wire_metrics(m,box,search)
    return [round(t,3) if t is not None else None for t in [*met['peak_position_mm'],met['lateral_width_6db_mm'],met['axial_width_6db_mm'],met['peak'],20*np.log10(met['peak']/np.percentile(m[roi],50)),met['clutter_p95_relative_db']]]
def load(name):
    s=files.load_session(out/(name+'.rf.npz'))
    cfg=copy.deepcopy(s.metadata['acquired_settings'])
    w.debug_apply(cfg,replay=True);h.recorded_tx_reference=s.tx_reference
    return s,cfg
def annotated(im,path,caption):
    # 13 pixels per mm on both axes.
    page=Image.new('RGB',(W+78,H+80),'#111820');d=ImageDraw.Draw(page)
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',14)
    page.paste(Image.fromqimage(im),(50,36))
    for v in range(10,51,5):
        y=36+round((v-box[2])*H/44)
        d.line((45,y,50,y),fill='#b3c1cc');d.text((41,y),str(v),anchor='rm',font=font,fill='white')
    for v in range(-15,16,5):
        xp=50+round((v-box[0])*W/34)
        d.line((xp,36+H,xp,42+H),fill='#b3c1cc');d.text((xp,44+H),str(v),anchor='mt',font=font,fill='white')
    d.text((50,6),caption,font=font,fill='white')
    d.text((6,6),'mm',font=font,fill='#b3c1cc')
    d.text((50+W//2,H+60),'Lateral position (mm)',anchor='mt',font=font,fill='#b3c1cc')
    page.save(path)
if __name__=='__main__':
    for name in ['baseline','near-gain','flat-gain']:
        s,cfg=load(name)
        rf=s.rf[:]
        if name=='baseline':
            m,im=render(rf[0]); annotated(im,out/'baseline.png','Baseline   |   One hardware sweep')
            print('original',measure(m),flush=True)
        h.state.update(cf=0,debug_view=1,dyn=55,gain=29,curve=.85)
        r1=rf[:8].mean(0);r2=rf[32:40].mean(0)
        m,im=render(r1); b,_=render(r2); dif,_=render((r1-r2)/2)
        valid=[i for i in range(48) if i not in (25,46)]
        v=rf[:,valid,:]
        print(name,measure(m), 'clip',np.mean((v<=-2048)|(v>=2047)), 'bg/floor',20*np.log10(np.linalg.norm(m[roi])/np.linalg.norm(dif[roi])), 'repeat',np.corrcoef(m[roi],b[roi])[0,1], 'bg median',np.median(m[roi]),flush=True)
        annotated(im,out/(name+'-das.png'),name+'   |   8-sweep ordinary DAS')
        s.close()
    h.stats['alive']=False
    ren.close();w.close()
