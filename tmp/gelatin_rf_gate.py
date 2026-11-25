from gelatin_analysis import *
from scipy.signal import hilbert, butter, sosfiltfilt
from PIL import ImageOps
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',15)
canvas=Image.new('RGB',(880,324),'#111820');draw=ImageDraw.Draw(canvas)
for i,name in enumerate(['flat-gain','verified-live']):
    s,cfg=load(name);a=s.rf[-8:].mean(0);fs=40
    bp=butter(3,[1,6],fs=40,btype='bandpass',output='sos')
    a=sosfiltfilt(bp,a,axis=-1)
    trace=np.abs(hilbert(a,axis=-1))
    zt=(11+np.arange(a.shape[1])/fs)*1.531/2
    mask=(zt>14)&(zt<23); env=trace[:,mask].T
    env[:,[25,46]]=0
    im=Image.fromarray((np.clip(1+20*np.log10(np.maximum(env,1e-10)/env.max())/40,0,1)*255).astype('uint8')).resize((384,230))
    x0=40+440*i; canvas.paste(im,(x0,44)); draw.text((x0,10),name+'  |  8 sweeps, 1–6 MHz',font=font,fill='white')
    for zmark in [14,16,18,20,22]:
        y=44+(zmark-14)*230/9;draw.text((x0-5,y),str(zmark),anchor='rm',font=font,fill='white')
    for e in [0,12,24,36,47]:draw.text((x0+(e+.5)*8,280),str(e),anchor='mt',font=font,fill='white')
    draw.text((x0+192,300),'Element ID',anchor='mt',font=font,fill='white')
    valid=np.array([j for j in range(48) if j not in (25,46)])
    print(name,'median peak and range in independent subapertures')
    for idx in np.array_split(valid,6):
        local=trace[idx][:,mask]
        print(idx[[0,-1]],np.round(np.quantile(zt[mask][local.argmax(1)],[.25,.5,.75]),3))
    for cf in [.28,.5,.75]:
        h.state.update(cf=cf,dyn=57,gain=40,curve=.85,mf=True,apod=.2,accept=25)
        mag,im=render(s.rf[-8:].mean(0))
        if name=='verified-live' and cf!=.28:annotated(im,out/f'verification-coherence-{cf}.png',f'Live verification   |   Coherence {cf:g}')
canvas.save(out/'wire-rf-gates.png')
h.stats['alive']=False;ren.close();w.close()
