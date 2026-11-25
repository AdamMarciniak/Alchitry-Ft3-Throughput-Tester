import json, math, re, collections, zipfile, hashlib
from pathlib import Path
import openpyxl

BASE=Path(__file__).resolve().parent
DEC=json.JSONDecoder()
def parse(stem):
    z=zipfile.ZipFile('D:/Downloads/'+stem+'.epro2')
    docs=[]
    for line_no,line in enumerate(z.read(stem+'.epru').decode('utf-8').splitlines(),1):
        if not line.strip(): continue
        h,j=DEC.raw_decode(line)
        tail=line[j:]
        assert tail.startswith('||'),(line_no,tail[:100])
        tail=tail[2:]
        v=None if tail=='|' else DEC.raw_decode(tail)[0]
        if h['type']=='DOCHEAD':
            d={'head':v,'records':[]}; docs.append(d)
        else: d['records'].append((h,v,line_no))
    return docs
def rec(d,t): return [(h,v,n) for h,v,n in d['records'] if h['type']==t and v is not None]
def attrs(d):
    a=collections.defaultdict(dict)
    for h,v,n in rec(d,'ATTR'): a[v.get('parentId','')][v['key']]=v['value']
    return a
def meta(d): return rec(d,'META')[0][1]
def nat(s): return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)',str(s))]
def transform(x,y,c):
    # Screen Y increases downward; positive rotations are counterclockwise.
    r=math.radians(c['rotation']); a=x*math.cos(r)+y*math.sin(r); b=-x*math.sin(r)+y*math.cos(r)
    if c['isMirror']: a=-a
    return (a+c['x'],b+c['y'])
def distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]; l2=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/l2)) if l2 else 0
    return math.dist(p,(a[0]+t*dx,a[1]+t*dy))
def onseg(p,a,b,tol=0.0001):
    dx,dy=b[0]-a[0],b[1]-a[1]; l2=dx*dx+dy*dy
    if l2==0:return math.dist(p,a)<=tol
    t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/l2
    return distance(p,a,b)<=tol
class UF:
    def __init__(self): self.p={}
    def find(self,a):
        self.p.setdefault(a,a)
        if self.p[a]!=a: self.p[a]=self.find(self.p[a])
        return self.p[a]
    def union(self,a,b): self.p[self.find(a)]=self.find(b)

def build(stem,board,bomfile,tolerance=0.25):
    ds=parse(stem); lib={d['head']['uuid']:d for d in ds}; page=next(d for d in ds if d['head']['docType']=='SCH_PAGE'); at=attrs(page)
    wires={h['id']:v for h,v,n in rec(page,'WIRE')}
    segs=[]; orphan=[]
    for h,v,n in rec(page,'LINE'):
        row=(v['lineGroup'],(v['startX'],v['startY']),(v['endX'],v['endY']),h['id'])
        (segs if v['lineGroup'] in wires else orphan).append(row)
    for wid,w in wires.items():
        for pts in w.get('dots',[]):
            for i in range(0,len(pts)-2,2):segs.append((wid,tuple(pts[i:i+2]),tuple(pts[i+2:i+4]),wid))
    comps=[]; labels=[]; allpins=[]; other=[]
    for h,c,n in rec(page,'COMPONENT'):
        cid=h['id']; ca=at[cid]; dev=lib.get(ca.get('Device')); da=meta(dev).get('attributes',{}) if dev else {}
        merged=dict(da); merged.update({k:v for k,v in ca.items() if v is not None})
        sym=lib[merged['Symbol']]; sa=attrs(sym); sm=meta(sym)
        pins=[]
        for ph,p,pn in rec(sym,'PIN'):
            if p.get('partId','')!=c.get('partId',''): continue
            pa=dict(sa[ph['id']]); pa.update({k:v for k,v in at.get(cid+ph['id'],{}).items() if v is not None})
            number=str(pa.get('Pin Number',pa.get('NUMBER','')))
            pin={'number':number,'name':str(pa.get('Pin Name',pa.get('NAME',''))),'type':pa.get('Pin Type',p.get('electric')),'xy':transform(p['x'],p['y'],c),'symbol_pin_id':ph['id'],'source_line':pn,'node':cid+':'+ph['id']}
            pins.append(pin)
        ref=ca.get('Designator')
        if ref:
            co={'ref':ref,'id':cid,'source_line':n,'symbol_id':merged['Symbol'],'device_id':merged.get('Device'),'symbol_title':sm['title'],'attrs':merged,'instance_attrs':ca,'pins':pins,'placement':c,'symbol_type':sm.get('docType')}
            for pin in pins: pin['endpoint']=f'{board}.{ref}.{pin["number"]}'; allpins.append(pin)
            comps.append(co)
        elif sm.get('docType') in (18,19):
            name=merged.get('Global Net Name') if sm.get('docType')==18 else merged.get('Name')
            assert len(pins)==1,(cid,sm,len(pins))
            labels.append({'name':name,'id':cid,'type':sm.get('docType'),'xy':pins[0]['xy'],'node':pins[0]['node'],'source_line':n})
        else: other.append({'id':cid,'meta':sm,'pins':pins})
    uf=UF(); joins=[]
    for wid in wires: uf.find(wid)
    # A WIRE's LINE segments share its electrical identity. Separate WIRE groups
    # join only at an endpoint-on-segment contact; interior crossings do not join.
    for i,(wid,a,b,lid) in enumerate(segs):
        for w2,c,d,l2 in segs[i+1:]:
            if wid!=w2 and uf.find(wid)!=uf.find(w2) and (onseg(a,c,d) or onseg(b,c,d) or onseg(c,a,b) or onseg(d,a,b)):
                uf.union(wid,w2); joins.append((wid,w2))
    point_nodes=allpins+labels
    for p in point_nodes:
        uf.find(p['node']);p['wire_hits']=sorted({wid for wid,a,b,lid in segs if onseg(p['xy'],a,b,tolerance)})
        p['exact_wire_hits']=sorted({wid for wid,a,b,lid in segs if onseg(p['xy'],a,b)})
        p['near_wire_hits']=[{'wire_id':wid,'distance':min(distance(p['xy'],a,b) for w,a,b,lid in segs if w==wid)} for wid in p['wire_hits'] if wid not in p['exact_wire_hits']]
        p['nearest_wire_distance']=min(distance(p['xy'],a,b) for w,a,b,lid in segs)
        for wid in p['wire_hits']:uf.union(p['node'],wid)
    for i,p in enumerate(point_nodes):
        for q in point_nodes[i+1:]:
            if math.dist(p['xy'],q['xy'])<=0.0001: uf.union(p['node'],q['node'])
    named=collections.defaultdict(list)
    for lab in labels:
        if lab['name']:named[lab['name']].append(lab['node'])
    for wid in wires:
        if at[wid].get('NET'):named[at[wid]['NET']].append(wid)
    for name,nodes in named.items():
        for node in nodes[1:]:uf.union(nodes[0],node)
    groups=collections.defaultdict(lambda:{'pins':[],'labels':[],'wires':[],'aliases':[]})
    for p in allpins: groups[uf.find(p['node'])]['pins'].append(p)
    for lab in labels:groups[uf.find(lab['node'])]['labels'].append(lab)
    for wid in wires:groups[uf.find(wid)]['wires'].append(wid)
    for name,nodes in named.items():groups[uf.find(nodes[0])]['aliases'].append(name)
    nets=[]; un=0
    for key,g in sorted(groups.items(),key=lambda kv:nat(min((p['endpoint'] for p in kv[1]['pins']),default='~'+kv[0]))):
        g['aliases']=sorted(set(g['aliases']),key=nat); g['pins'].sort(key=lambda p:nat(p['endpoint']))
        if g['aliases']:name=g['aliases'][0]
        elif g['pins']:name='N_'+g['pins'][0]['endpoint'].split('.',1)[1].replace('.','_')
        else:un+=1;name=f'UNATTACHED_{un:03d}'
        g['id']=f'{board}:{name}'
        for p in g['pins']:p['net']=g['id'];p['status']='connected' if len(g['pins'])>1 else ('single_pin_net' if g['wires'] or g['labels'] else 'unconnected')
        nets.append(g)
    wb=openpyxl.load_workbook('D:/Downloads/'+bomfile,data_only=False)
    rows=[];bm={}
    for sh in wb:
        vals=list(sh.values);headers=vals[0]
        for rno,valsrow in enumerate(vals[1:],2):
            row=dict(zip(headers,valsrow))
            if not row.get('Designator'):continue
            row.update(sheet=sh.title,row=rno);refs=[r.strip() for r in row['Designator'].split(',')];assert len(refs)==row['Quantity']
            rows.append(row)
            for ref in refs:assert ref not in bm;bm[ref]=row
    for c in comps:c['bom']=bm.get(c['ref'])
    result={'board':board,'stem':stem,'bomfile':bomfile,'schematic':meta(next(d for d in ds if d['head']['docType']=='SCH')),'page':meta(page),'page_id':page['head']['uuid'],'components':sorted(comps,key=lambda c:nat(c['ref'])),'nets':sorted(nets,key=lambda g:nat(g['id'])),'bom_rows':rows,'bom_only':sorted(set(bm)-{c['ref'] for c in comps},key=nat),'other':other,'texts':[{'id':h['id'],**v} for h,v,n in rec(page,'TEXT')],'stats':{'components':len(comps),'pins':len(allpins),'nets':len(nets),'wires':len(wires),'wire_segments':len(segs),'orphan_line_segments':len(orphan),'labels':len(labels),'geometric_wire_joins':len(joins)},'orphan_lines':orphan}
    (BASE/(board+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(board,result['stats'],'BOM only',result['bom_only'],'schematic only',[c['ref'] for c in comps if not c['bom']]);print('pin status',collections.Counter(p['status'] for p in allpins));print('aliases',[(g['id'],g['aliases']) for g in nets if len(g['aliases'])>1]);print('nonpart',[(o['meta']['title'],len(o['pins'])) for o in other]);print('unconnected',[(p['endpoint'],p['name'],p['xy']) for p in allpins if p['status']=='unconnected']);print('single pin',[(g['id'],g['pins'][0]['endpoint']) for g in nets if len(g['pins'])==1 and g['pins'][0]['status']=='single_pin_net'])
    return result
if __name__=='__main__':
    build('pulser-schematic','PULSER','BOM_Pulser_Schematic1_2026-09-07.xlsx')
    build('afe-schematic','AFE','BOM_ADC_Schematic2_2026-09-07.xlsx')
