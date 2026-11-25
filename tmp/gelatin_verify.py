from gelatin_analysis import *
s,cfg=load('verified-live')
r=s.rf[:]
m,im=render(r[-8:].mean(0))
annotated(im,out/'verified-wire-and-gel.png','Live verification   |   Wire and surrounding gelatin')
print('wire',measure(m))
valid=np.delete(r,[25,46],axis=1)
side=(x[None,:]>-1)&(x[None,:]<7)&(z[:,None]>17)&(z[:,None]<21)
met=wire_metrics(m,box,search)
result=json.loads((out/'measurements.json').read_text())
result['verified_live']={'wire_position_mm':met['peak_position_mm'],'width_mm':[met['lateral_width_6db_mm'],met['axial_width_6db_mm']],'wire_peak_vs_local_p95_db':float(20*np.log10(met['peak']/np.percentile(m[side],95))),'clipped_samples_active_elements':int(np.count_nonzero((valid<=-2048)|(valid>=2047))),'valid_frames':sum(q['valid'] for q in s.quality),'central_gel_median_gray':float(np.median(array(im)[roi]))}
files.atomic_json(out/'measurements.json',result)
print(result['verified_live'])
for name in ['live-viewer','live-bmode']:
    img=Image.open(out/(name+'.png'))
    img.thumbnail((1040,560));img.save(root/'tmp'/(name+'-preview.png'))
print(cfg['summary'],cfg['stream'],cfg['receive']['avg_held'],cfg['transmit']['armed'])
h.stats['alive']=False;ren.close();w.close()
