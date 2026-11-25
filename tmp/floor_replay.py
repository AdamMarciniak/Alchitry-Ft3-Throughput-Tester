"""Replay the fixed phantom and compare it with an ideal planar mirror and point."""
from gelatin_analysis import h, w, ren, files, root, wire_metrics
import numpy as np
import json
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import least_squares

source = root / 'bench_runs/three-position-rx'
out = root / 'bench_runs/container-floor'
out.mkdir(exist_ok=True)
db = lambda a: 20 * np.log10(np.maximum(a, 1e-15))

def view(an, bounds):
    x0, x1, z0, z1 = bounds
    nx, nz = round(20*(x1-x0)), round(20*(z1-z0))
    mag, _ = ren.render(an, bounds, nx, nz)
    x = x0 + (np.arange(nx)+0.5)*(x1-x0)/nx
    z = z0 + (np.arange(nz)+0.5)*(z1-z0)/nz
    return mag, x, z

def fit_floor(view_data):
    mag, x, z = view_data
    bins = np.arange(-16, 16.01, .5)
    ridge = np.array([z[np.argmax(mag[:,abs(x-b)<.25].mean(1))] for b in bins])
    mid = abs(bins) <= 6
    def residual(p):
        return ridge[mid] - (p[0] + p[1]*bins[mid])
    b, slope = least_squares(residual, [44.5,.07], loss='soft_l1', f_scale=.1).x
    err = residual((b,slope))
    return dict(center_mm=b, slope_deg=np.degrees(np.arctan(slope)), slope=slope,
                central_p95_abs_mm=np.percentile(abs(err),95), central_rms_mm=np.sqrt(np.mean(err**2)))

def ideal(an, floor, point):
    # Mirror the source across z=b+mx. Its distance to the receiver is the
    # exact specular round-trip path in a uniform medium for an infinite plane.
    elements = h.elem_uniform()[:,:2].astype(float) * 1000
    ids = np.arange(len(elements))
    if h.pulser.shot_method == 3:
        tx = np.repeat(ids,3)
        rx = np.clip(ids[:,None]+np.array(h.RX_OFFSETS),0,len(ids)-1).ravel()
    else:
        tx = rx = ids
    origin, recv = elements[tx], elements[rx]
    normal = np.array([-floor['slope'],1.])
    mirror = origin + 2*(floor['center_mm']-origin@normal)[:,None]*normal/(normal@normal)
    paths = [np.linalg.norm(mirror-recv,axis=1),
             np.linalg.norm(origin-point,axis=1)+np.linalg.norm(recv-point,axis=1)]
    t = np.arange(an.shape[1])/h.FS_HZ*1e6 + h.state['dly_us'] - h.state['t0_ns']/1000
    iq = np.zeros(an.shape[:2],np.complex64)
    for path in paths:
        dt = t[None,:] - path[:,None]*1000/h.state['c']
        iq += np.exp(-.5*(dt/.16)**2 + 2j*np.pi*3.5*dt)
    return np.stack((iq.real,iq.imag),axis=2)

def raw_floor(an):
    E = h.elem_uniform()[:,:2].astype(float)*1000
    dist = (np.arange(an.shape[1])/h.FS_HZ + h.state['dly_us']*1e-6 -
            h.state['t0_ns']*1e-9)*h.state['c']*500
    ok = h.alive_mask() > 0
    same = an[::3] if h.pulser.shot_method == 3 else an
    window = (dist>42)&(dist<47.5)
    peaks = dist[window][np.argmax(np.linalg.norm(same[ok][:,window],axis=2),axis=1)]
    ex, ez = E[ok].T
    def residual(p):
        b,m = p
        return peaks - (b+m*ex-ez)/np.hypot(1,m)
    b, m = least_squares(residual,[44.5,.07],loss='soft_l1',f_scale=.1).x
    return dict(center_mm=b,slope_deg=np.degrees(np.arctan(m)),
                p95_abs_range_residual_mm=np.percentile(abs(residual((b,m))),95))

floor_bounds = [-17,17,40,49]
wire_bounds = [-14,14,14,22]

def wire_data(an):
    mag,x,z = view(an,wire_bounds)
    met = wire_metrics(mag,wire_bounds,[.4,3.2,16.5,18.6])
    px,pz = met['peak_position_mm']
    side = (abs(x[None,:]-px)>=7)&(abs(x[None,:]-px)<=15)&(abs(z[:,None]-pz)<1.5)
    return (mag,x,z),dict(point_mm=[px,pz],lat_mm=met['lateral_width_6db_mm'],
                           ax_mm=met['axial_width_6db_mm'],far_contrast_db=db(met['peak']/np.percentile(mag[side],95)))

def figure(measured,simulated,fit):
    paper=Image.new('RGB',(1230,558),'#f8fafb')
    draw=ImageDraw.Draw(paper)
    font=lambda size: ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',size)
    ink='#172935'
    def label(x,y,value,size=16,anchor='la'):
        draw.text((x,y),value,font=font(size),anchor=anchor,fill=ink)
    scale=16
    for k,(values,title) in enumerate([(measured,'Recorded phantom'),(simulated,'Simulated flat mirror and one point')]):
        center=330+600*k
        label(center,24,title,23,'mm')
        for row,(mag,x,z) in enumerate(values):
            bounds = floor_bounds if row==0 else wire_bounds
            xmin,xmax,zmin,zmax=bounds
            width,height=scale*(xmax-xmin),scale*(zmax-zmin)
            x0,y0=center-width//2,(75 if row==0 else 300)
            panel=Image.fromarray(np.uint8(np.clip((db(mag/mag.max())+50)/50,0,1)*255))
            paper.paste(panel.resize((width,height),Image.Resampling.BILINEAR),(x0,y0))
            label(x0,y0-25,('Bottom' if row==0 else 'Wire')+' depth (mm)',15)
            for tick in range(zmin,zmax+1,2):
                py=y0+(tick-zmin)*scale
                draw.line((x0-4,py,x0-1,py),fill=ink)
                label(x0-8,py,str(tick),14,'rm')
            for tick in range(-15,16,5):
                if not xmin<=tick<=xmax: continue
                px=x0+(tick-xmin)*scale
                draw.line((px,y0+height,px,y0+height+4),fill=ink)
                label(px,y0+height+6,str(tick),14,'mt')
            if row==1: label(center,y0+height+40,'Lateral position (mm)',15,'mm')
            if row==0:
                for p in np.arange(xmin,xmax-.3,.78):
                    if abs(p)<7: continue
                    coords=[]
                    for v in (p,p+.42):
                        coords.extend((x0+(v-xmin)*scale,y0+(fit['center_mm']+fit['slope']*v-zmin)*scale))
                    draw.line(coords,fill='#45d4c2',width=2)
    draw.line((59,514,96,514),fill='#129987',width=3)
    label(106,513,'Straight-line fit to the central 12 mm, extended',16,'lm')
    label(660,513,'Grayscale spans 50 dB relative to each panel’s peak.',16,'lm')
    paper.save(out/'floor-and-wire.png')

def compare_regions(an, floor_data, wire_data, fit):
    mag,x,z=floor_data
    dz=z[:,None]-(fit['center_mm']+fit['slope']*x)
    mid=(abs(x[None,:])<=6)&(abs(dz)<.3)
    wing=(abs(x[None,:])>=8)&(abs(x[None,:])<=15)&(dz<-.7)&(dz>-3.5)
    gel,_,_=view(an,[-5,5,29,37])
    wire_peak=wire_data[0].max()
    return dict(upper_wing_to_floor_db=db(np.percentile(mag[wing],95)/np.percentile(mag[mid],95)),
                gel_rms_to_wire_db=db(np.sqrt(np.mean(gel**2))/wire_peak))

def run():
    results={}
    for label in ['final-live','three-rx-repeat','broad-matched-repeat']:
        s=files.load_session(source/(label+'.rf.npz'))
        try:
            w.debug_apply(s.metadata['acquired_settings'],replay=True)
            h.recorded_tx_reference=s.tx_reference
            raw=s.rf[:8].mean(0)
            n=h.cfg['samps']
            an=h.prepare_analytic(raw,n)
            base_apod=h.state['apod']
            base_geom=h.geom.copy()
            floor=view(an,floor_bounds)
            fit=fit_floor(floor)
            wire,wm=wire_data(an)
            data=dict(raw_plane=raw_floor(an),displayed_floor=fit,wire=wm)
            data['regions']=compare_regions(an,floor,wire,fit)
            if label=='final-live':
                control=ideal(an,fit,np.array(wm['point_mm']))
                simfloor=view(control,floor_bounds)
                simwire,_=wire_data(control)
                figure([floor,wire],[simfloor,simwire],fit)
                data['ideal_floor']=fit_floor(simfloor)
                # Quantify an outer wing only where the simulated return is above -50 dB.
                sm,sx,sz=simfloor
                strength=db(sm.max(axis=0)/sm.max())
                for pos in [-14,-12,-10,0,5,8,10,12,14]:
                    j=np.argmin(abs(sx-pos))
                    print('mirror',round(sx[j],1),round(sz[np.argmax(sm[:,j])],2),
                          round(fit['center_mm']+fit['slope']*sx[j],2),round(strength[j],1))
            for variant in ['stronger_taper','documented_geometry','frequency_compounding']:
                if variant=='stronger_taper':
                    h.state['apod']=.75
                if variant=='documented_geometry':
                    h.geom.update(pitch_mm=.3375,R_mm=67.52)
                    h.rebuild_geometry()
                if variant=='frequency_compounding':
                    h.state['freq_comp']=True
                frame=h.prepare_analytic(raw,n) if variant=='frequency_compounding' else an
                test_wire,metric=wire_data(frame)
                test_floor=view(frame,floor_bounds)
                data[variant]=dict(wire=metric,floor=fit_floor(test_floor),
                                   regions=compare_regions(frame,test_floor,test_wire,fit))
                h.state.update(apod=base_apod,freq_comp=False)
                h.geom.update(pitch_mm=base_geom['pitch_mm'],R_mm=base_geom['R_mm'])
                h.rebuild_geometry()
            results[label]=data
            print(label,fit,wm,flush=True)
        finally:
            s.close()
    with (out/'measurements.json').open('w') as f:
        json.dump(results,f,indent=2,default=float)

if __name__=='__main__':
    try:
        run()
    finally:
        h.stats['alive']=False
        ren.close()
        w.close()
