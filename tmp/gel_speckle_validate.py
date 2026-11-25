from gel_speckle import *
groups=[]
for label,par in [('original',(20,.45,True,3.5,5)),('narrow',(20,.45,False,5,4)),('detail',(25,.3,False,5,4)),('wide',(30,.3,False,5,4))]:
    setup(*par);h.state['gain']=32
    b,im=get(source,0)
    h.state['gain']=min(40,32+int(round((55-b['gray'])*66/255))) if label!='original' else 32
    a,im=get(raw[40:48].mean(0),0);m1,_=render(raw[:8].mean(0));m2,_=render(raw[40:48].mean(0))
    side=(abs(x[None,:]-2)>5)&(abs(z[:,None]-18.5)<3)
    a['outer99db']=float(20*np.log10(np.percentile(m2[side],99)/wire_metrics(m2,box,[-1,5,17,20.5])['peak']))
    a['repeat']=float(np.corrcoef(m1[roi],m2[roi])[0,1]);a['gain']=h.state['gain']
    print(label,a);groups.append((label,a))
    annotated(im,out/('speckle-'+label+'.png'),{'original':'Original preset','detail':'Detail preset','narrow':'20 degree acceptance','wide':'30 degree acceptance'}[label])
files.atomic_json(out/'speckle-held-back.json',dict(groups))
h.stats['alive']=False;ren.close();w.close()
