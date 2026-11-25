from gel_speckle import *
path=root/'host/presets/gelatin-fine-texture.json'
partial={'settings_schema':1,'note':'Fine texture in the wire and psyllium phantom. Tested on the saved final-live RF capture.',
         'receive':{'bandpass_on':True,'band_f0_mhz':5.,'band_bw_mhz':4.,'matched_filter':False,'frequency_compounding':False,'avg_sweeps':8},
         'beamformer':{'apod':.45,'cf':.25,'accept_deg':20,'dead':[25,46]},
         'display':{'gain_db':36,'dyn_db':66,'curve':.85,'auto_gain':False,'debug_view':0}}
files.atomic_json(path,partial)
checked=files.load_settings(path,cfg)
assert checked['transmit']['chirp_f0_mhz']==cfg['transmit']['chirp_f0_mhz'] and not checked['receive']['matched_filter']
shape=(336,432);box2=[-7,7,17,35];canvas=Image.new('RGB',(800,524),'#111820');d=ImageDraw.Draw(canvas)
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17); small=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',13)
for i,(params,gain,label) in enumerate([((20,.45,True,3.5,5),32,'Original'),((20,.45,False,5,4),36,'Fine texture')]):
    setup(*params);h.state.update(gain=gain,debug_view=0)
    record=raw[-8:].mean(0)
    mag,im=ren.render(h.prepare_analytic(record,record.shape[1]),box2,*shape)
    left=49+390*i;top=43
    d.text((left,10),label,font=font,fill='white')
    canvas.paste(Image.fromqimage(im),(left,top))
    for zz in [18,20,25,30,35]:
        yy=top+(zz-17)*24;d.text((left-5,yy),str(zz),font=small,anchor='rm',fill='#c1cbd6')
    for xx in [-5,0,5]:d.text((left+(xx+7)*24,top+435),str(xx),font=small,anchor='mt',fill='#c1cbd6')
d.text((400,502),'Lateral position and depth in mm',anchor='mt',font=small,fill='#c1cbd6')
canvas.save(out/'speckle-comparison.png')
h.stats['alive']=False;ren.close();w.close()
