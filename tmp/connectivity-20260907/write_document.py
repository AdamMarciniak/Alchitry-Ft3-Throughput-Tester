import json, hashlib, re, collections
from pathlib import Path
from extract import BASE, nat, parse, rec, meta

BOARDS=[json.loads((BASE/(b+'.json')).read_text(encoding='utf-8')) for b in ['PULSER','AFE']]
SOURCE_BOARDS=json.loads(json.dumps(BOARDS))
BRIDGES=[('U3','NO11',17,32),('U7','NO5',33,48),('U1','NO7',49,64)]
for b in BOARDS:
    mappings={}
    for c in b['components']:
        for p in c['pins']:p['saved_net']=p['net']
    if b['board']=='PULSER':
        for mux,label,lo,hi in BRIDGES:
            for c in b['components']:
                if c['ref'] in {f'R{r}' for r in range(lo,hi+1)}:
                    assert any(p['net']=='PULSER:'+label for p in c['pins'])
                    for p in c['pins']:mappings[p['net']]='PULSER:'+label
        grouped=collections.defaultdict(list)
        for g in b['nets']:grouped[mappings.get(g['id'],g['id'])].append(g)
        merged=[]
        for nid,gs in grouped.items():
            g={'id':nid,'saved_net_ids':sorted(x['id'] for x in gs),'aliases':sorted({a for x in gs for a in x['aliases']})}
            for field in ['pins','labels','wires']:g[field]=[v for x in gs for v in x[field]]
            for p in g['pins']:p['saved_net']=p['net'];p['net']=nid
            g['pins'].sort(key=lambda p:nat(p['endpoint']));merged.append(g)
        b['nets']=sorted(merged,key=lambda g:nat(g['id']))
        for c in b['components']:
            for p in c['pins']:p['net']=mappings.get(p['net'],p['net'])
    for g in b['nets']:g.setdefault('saved_net_ids',[g['id']])
OUT=Path('C:/Users/Adam/usb3-tester/docs/schematic-connectivity-2026-09-07.md')
lines=[]
def add(s=''):lines.append(s)
def code(s):return '`'+str(s).replace('`','\\`').replace('|','\\|').replace('\n',' / ')+'`'
def j(s):return json.dumps(s,ensure_ascii=False,separators=(',',':'))
def tab(headers,rows):
    add('| '+' | '.join(headers)+' |');add('| '+' | '.join(['---']*len(headers))+' |')
    for row in rows:add('| '+' | '.join(str(x) for x in row)+' |')
    add()
def co(b,r):return next(c for c in b['components'] if c['ref']==r)
def pi(c,n):return next(p for p in c['pins'] if p['number']==str(n))

add('# Pulser and AFE connectivity reference with confirmed solder bridges')
add()
add('Date: 2026-09-07. Format: UTF-8 Markdown. Coverage: 227 placed components and 1,179 symbol terminals across two EasyEDA Pro schematics, plus the owner-confirmed physical bridges on all three leaf muxes.')
add()
add('## 1. Scope and interpretation')
add()
add('This document combines the supplied schematic projects, BOMs, and the owner’s physical-build clarification into a component-to-net map and a net-to-component map. The primary pin tables and net records incorporate the confirmed solder bridges. Each changed pin also retains its saved-schematic net ID, and each net record retains its constituent saved net IDs. Every placed component and every pin in its selected library symbol is included, even when absent from ordinary package pin counts or left unconnected.')
add()
add('**Verification limit:** this is a reconstruction from the saved project records, not an EasyEDA-generated netlist. A 0.25 schematic-coordinate-unit tolerance is used for pin/port-to-wire matching because the files contain small coordinate offsets. Every tolerance-dependent contact is identified in Section 8. Four additional near contacts at 0.31496063 units are left unresolved in Section 2. The document preserves these limits so an LLM cannot mistake inferred contact for native-netlist confirmation.')
add()
add('- Component IDs use `BOARD.REF`, for example `PULSER.U1` and `AFE.U1`; they are different devices. Pin endpoints use `BOARD.REF.PIN`, with BGA pin numbers preserved as strings such as `AFE.U1.A1`.')
add('- Net IDs use `BOARD:LABEL`. Exact spelling, spaces, signs, and case are preserved. Labels on different boards do not establish a cable connection. Within one board, identical net-port/global-net names are merged.')
add('- Unnamed nets receive a deterministic document ID `BOARD:N_REF_PIN`, based on a naturally sorted endpoint. These IDs are generated for this document, not source labels.')
add('- Pins on the same net are directly electrically connected by reconstructed wiring or an owner-confirmed solder bridge. Components do not otherwise merge nets. No internal IC switching state, diode conduction state, unconfirmed solder bridge, or component population is assumed. Leaf-bank inputs are common within each mux; the three banks retain separate root-switch outputs.')
add('- `CONNECTED` means a net has two or more component terminals. `SINGLE_PIN_NET` means a wire or label exists but only one component terminal was found. `UNCONNECTED` means no wire/port/other pin contact was found under the stated reconstruction rule. It does not by itself mean intentional no-connect.')
add('- A pin named `NC`, `DNC`, or `COM` is recorded literally. Names do not override wiring. In particular, the literal net name `3.3V NC` is a connected pulser supply net, despite containing the letters NC.')
add('- `EXACT` means a contact within 0.0001 coordinate units. `NEAR` means a larger contact offset within 0.25 units. These are geometric evidence classes, not electrical safety or design-quality ratings. Net records identify near pins and near label IDs so dependence on a displaced label remains visible.')
add('- BOM metadata comes from the supplied spreadsheet row; symbol pin names and numbers come from the embedded symbol library. Source notes and placeholder wording are quoted as design data and are not instructions to alter the circuit.')
add()
add('### Source files and coverage')
add()
tab(['Board','Project / schematic / sheet','Components','Symbol terminals','Connected nets¹','Single-pin nets','Unconnected terminals'],[
    [b['board'],code(b['stem']+'.epro2')+' / '+code(b['schematic']['title'])+' / '+code(b['page']['title']),len(b['components']),b['stats']['pins'],sum(len(g['pins'])>=2 for g in b['nets']),sum(len(g['pins'])==1 and g['pins'][0]['status']=='single_pin_net' for g in b['nets']),sum(p['status']=='unconnected' for c in b['components'] for p in c['pins'])] for b in BOARDS])
add('¹ Connected nets contain at least two symbol terminals. AFE also contains one wire group with no component terminals or net labels; it is listed separately. Both BOM reference sets exactly match their corresponding schematic reference sets. All 55 populated BOM rows have quantities equal to their listed designator counts.')
add()
for b in BOARDS:
    for f in [b['stem']+'.epro2',b['bomfile']]:
        p=Path('D:/Downloads')/f;add('- '+code(f)+': SHA-256 '+code(hashlib.sha256(p.read_bytes()).hexdigest())+'.')
add()
add('## 2. Exceptions that must remain visible')
add()
add('### 2.0 Owner-confirmed physical solder bridges');add()
add('Owner clarification received 2026-09-07: “the solder gaps for the three leaf muxes have all been physically bridged by me” and “all three tree muxes have all their inputs connected together.” This is treated as authoritative physical-build data for the leaf-mux COM/input gaps. Matching those gaps to the supplied schematic identifies 48 Blob-Standin positions: R17 through R64.');add()
tab(['Leaf mux','Physically bridged gap designators','Common input net','Root switch endpoint'],[[code('PULSER.'+m),code(f'R{lo}–R{hi}')+' (each gap closed)',code('PULSER:'+label),code('PULSER.U5.'+{'NO11':'25','NO5':'14','NO7':'18'}[label])] for m,label,lo,hi in BRIDGES])
add('For each leaf mux, COM0 through COM15 (pins 1, 3, 5, 7, 11, 13, 15, 17, 20, 22, 24, 26, 30, 32, 34, and 36) are now one common input node. Each of the 48 listed gap symbols has pin 1 physically shorted to pin 2. The three common nodes are NO11 for U3, NO5 for U7, and NO7 for U1. Their normally-open/output pins remain distinct switched channels. No permanent short between these three common nodes is added.');add()
add('The root mux U5’s 13 remaining Blob-Standin positions (R2–R8, R10, R12–R16) are not covered by the leaf-gap confirmation. Their original separate-net treatment remains. The primary as-built graph has 48 fewer nets than the saved-schematic reconstruction. No source schematic or BOM was edited.');add()
add('### 2.1 Four unresolved pulser contacts near ground')
add()
add('In the saved-schematic reconstruction before physical overrides, ground wire group `0aca1b973681fa10` passes 0.31496063 coordinate units from the following resistor pins. These pins already have a direct wire to a switch COM pin. At tolerance 0.25 they remain separate from ground; at 0.5 all four nets merge into ground. Both interpretations must remain possible until checked with an EasyEDA netlist export. No other saved-schematic component-net membership changes when increasing the matching tolerance from 0.25 to 0.5.')
add()
tab(['Saved schematic net','Endpoints before physical bridges','Additional possible connection'],[[code('PULSER:N_R'+str(r)+'_2'),code(f'PULSER.R{r}.2')+', '+code(f'PULSER.U3.{pin}'),'PULSER:GND (unresolved)'] for r,pin in [(18,30),(19,32),(20,34),(21,36)]])
add('The separate net IDs in this table identify the saved schematic before physical bridges. In the primary as-built graph, all four belong to `PULSER:NO11` because their gaps are closed. Therefore, if any of these near-ground contacts is recognized as connected by EasyEDA or exists physically, the entire U3 common-input bank is on ground. The owner’s bridge confirmation does not itself establish or rule out that ground connection. Section 8 retains the smaller offsets accepted by the reconstruction.')
add()
add('### 2.2 Population, placeholders, and pin-count discrepancies')
add()
add('- `PULSER.U1` and `PULSER.U7` are included in BOM row 19, but their schematic instance property `Add into BOM` is `no`. Their connectivity remains included; installed population is unresolved.')
add('- 61 pulser resistor designators have value/comment `Blob-Standin`, with no manufacturer or supplier part specified. The 48 leaf positions R17–R64 are physically bridged per owner confirmation. The other 13 positions retain their original separate-net treatment.')
add('- `PULSER.C25` has value/comment `PLACEHOLDER FOR RESISTOR LATER`, while the BOM still lists capacitor part `CL10B104KA8WPNC` and footprint `C0603`. Its intended eventual type/value is unresolved. The two-terminal connection is preserved.')
add('- `PULSER.U9` is called `48 Pin Connector`, but the symbol contains pins `1` through `102` and the BOM footprint is `100P-JMDSS-G-1-TF`. All 102 terminals are included. The intended connector model/contact count cannot be settled from the name alone.')
add('- `AFE.U5` and `AFE.U6` have 82 symbol terminals each although their part name specifies an 80-position connector. The additional symbol terminals are retained exactly. `AFE.U7` has seven symbol terminals and BOM comment `DSC1123 40Mhz OSC`, with no manufacturer part number supplied.')
add('- `PULSER.SET` and `PULSER.GND` are aliases of the same wired net. The canonical document ID is `PULSER:GND`. The four MAX14866 SET pins are therefore on ground in this reconstruction.')
add('- `PULSER.CN1.2` carries the literal label `1.8V NC` but has no second component endpoint. `AFE:41` reaches only `AFE.U6.41`; `AFE.CN1.15` remains unconnected. Do not invent a missing wire between them.')
add()
add('### 2.3 Separate projects do not define an inter-board cable')
add()
add('There is no authoritative inter-board cable map in the supplied files. In particular, identically numbered CN1 connectors are not assumed to mate pin-for-pin. The following is a **candidate reversal hypothesis only**: `PULSER.CN1.n` could pair with `AFE.CN1.(21-n)`. It aligns the 5 V, 3.3 V, 1.8 V, and ground positions by label. It is not included in either board netlist and is not a wiring instruction.')
add()
rows=[]
for n in range(1,21):
    pp=pi(co(BOARDS[0],'CN1'),n); ap=pi(co(BOARDS[1],'CN1'),21-n)
    rows.append([code(pp['endpoint']),code(pp['net']) if pp['status']!='unconnected' else 'UNCONNECTED',code(ap['endpoint']),code(ap['net']) if ap['status']!='unconnected' else 'UNCONNECTED'])
tab(['Pulser pin','Pulser net','Candidate AFE pin','AFE net'],rows)
add('Similarly, `PULSER.RF2.5` is the pulser receive-side signal and `AFE.RF1.5` is the AFE input-side signal. A cable between these SMA ports is a plausible system connection, but neither archive specifies it. SMA pins 1–4 are ground on each board. Their physical cable connection remains unspecified.')
add()
add('## 3. Circuit paths for orientation')
add()
add('These descriptions summarize the pin tables. Arrows express a path through named component terminals, not a short circuit across the component or a guarantee of signal direction in every operating state.')
add()
add('### Pulser')
add()
add('- High-voltage connector: `CN2.1 = -100V`, `CN2.2 = GND`, `CN2.3 = +100V`. MOSFET source pins are `Q1.1/SN = -100V` and `Q1.3/SP = +100V`.')
add('- Driver inputs: `CN1.15 → SIG1_IN → U6.1/INA`; `CN1.11 → SIG2_IN → U6.3/INB`; `CN1.19 → DRIVER_EN → U6.12/OE`.')
add('- Positive gate path: `U6.9/OUTA → C26.1`, through C26 to `C26.2 → C24.2`, through C24 to `C24.1 → P_DRIVER_OUT_A → Q1.4/GP`.')
add('- Negative gate path: `U6.7/OUTB → C3.1`, through C3 to `C3.2 → C25.1`, through unresolved placeholder C25 to `C25.2 → N_DRIVER_OUT_B → Q1.2/GN`.')
add('- Pulse output: `Q1.5/DP` and `Q1.6/DP` share `D1.1`; `Q1.7/DN` and `Q1.8/DN` share `D1.2`; `D1.3` is on `PULSE_OUT`. `U4.3/B` is also on `PULSE_OUT`. `U4.1/A`, `D2.1`, `D2.2`, and `RF2.5` share the receive-side net; `D2.3` is ground. `U4.2/COM` is unconnected in the saved schematic.')
add('- Serial switch chain: `CN1.7/DIN → U5.44/DIN`; `U5.39/DOUT → DOUT1 → U7.44/DIN`; `U7.39/DOUT → DOUT2 → U1.44/DIN`; `U1.39/DOUT → DOUT3 → U3.44/DIN`; `U3.39/DOUT → DOUT_READBACK → CN1.18`. The U1/U7 population discrepancy affects any physical implementation of this chain.')
add('- On all four MAX14866 symbols, pin 38 is `LE`, pin 45 is `CLK`, pin 47 is `CLR`, and pin 46 is `SET`, aliased to ground. Pin 40 uses the literal supply label `3.3V NC`; pin 43 uses `+5V`. All COM/NO pins and every placeholder resistor are listed individually below.')
add('- Inverter: `U2.2/IN = +5V`, `U2.1/OUT = -5V`, `U2.4/GND = GND`; `C9` bridges `U2.3/CFLY-` and `U2.5/CFLY+`.')
add()
add('### AFE / ADC')
add()
add('- Receive path: `RF1.5 → R6.1`; R13 connects this node to ground. Through R6 (33 Ω) the path reaches `R6.2`, `D1.1`, `D1.2`, and `C2.1`; `D1.3` is ground. Through C2 (100 nF), `C2.2 → IN1 → U1.A1`.')
add('- USB-derived 5 V path: `5V-USB → L3.1`, through L3 (4.7 µH) to `L3.2/L7.1`, through L7 to `L7.2/+5_VDD`. The complete capacitor branches are in the component tables.')
add('- 3.3 V regulator path: `+5_VDD → L1.1 → L1.2 → U2.2/IN` and `U2.1/EN`; `U2.4/OUT → L2.1 → L2.2 → +3.3_VDD`.')
add('- 1.8 V regulator path: `+5_VDD → L10.1 → L10.2 → U12.2/IN` and `U12.1/EN`; `U12.4/OUT → L11.1 → L11.2 → +1.8_LVDD`.')
add('- Clock: `U7.4/OUT+ → C53.2`, through C53 to `CLKP → U1.L1`; `U7.5/OUT- → C66.2`, through C66 to `CLKM → U1.K1`. R2 (100 Ω) bridges CLKP and CLKM. The 40 MHz designation is the source BOM comment.')
add('- Connected ADC output pair: `U1.R4/OUT1M → OUT1M → U5.51`; `U1.P4/OUT1P → OUT1P → U5.53`. Frame clock: `U1.N9/FCLKP → U5.48` and `U1.N8/FCLKM → U5.46`. Lane clock: `U1.N1/LCLKP → U5.47` and `U1.N2/LCLKM → U5.45`.')
add('- AFE control: `U6.70 → ADS_RST → U1.H9`; `U6.72 → R5 → SDATA → U1.H8`; `U6.76 → CS → U1.H7`; `U6.78 → R1 → SCLK → U1.H6`. These U6 references identify the connector on the AFE board.')
add('- DAC control: AFE connector U5 pin 77 reaches `DAC_SYNC` through R9; pin 76 reaches `DAC_SCLK` through R10; pin 78 reaches `DAC_SDA` through R11. These nets reach U3 pins 9, 6, and 7 respectively.')
add('- Gain-control path: `U3.2/VouτB → R16.2`, through R16 (200 Ω) to `R16.1 → VCNTL → U1.D2`; C42 (470 pF) connects VCNTL to ground. The source pin spelling `VouτB` is preserved. U3 output pins 1, 4, and 5 are unconnected.')
add('- Reference: `U4.3/EN` and `U4.4/VIN` use `+1.8_LVDD`; `U4.6/VREF → 1.2V VREF → U3.10/REFIN`.')
add()
add('## 4. Component and pin tables')
add()
add('For a pin’s complete set of directly connected peers, find its primary net ID in Section 5. All endpoints in that record are connected under the stated reconstruction and confirmed-bridge rules. `Saved net` preserves the pre-bridge schematic ID when different; `same` means unchanged. `NEAR` refers to Section 8 and describes the source pin-to-wire geometry, not the physical solder bridge. A pin can have exact wire contact on a net whose label contact is NEAR; this is captured in the net record. Empty BOM fields are rendered as `not specified`.')
add()
for b in BOARDS:
    add('### '+b['board']+' components');add()
    for c in b['components']:
        bm=c['bom'];ref=b['board']+'.'+c['ref']
        add('#### '+ref+' — '+str(bm['Comment'] or c['symbol_title']));add()
        add('BOM: '+code(b['bomfile'])+', sheet '+code(bm['sheet'])+', row '+str(bm['row'])+' (item '+str(bm['No.'])+').')
        add()
        add('Value: '+code(bm['Value'] or 'not specified')+'. Manufacturer part: '+code(bm['Manufacturer Part'] or 'not specified')+'. Manufacturer: '+code(bm['Manufacturer'] or 'not specified')+'.')
        add()
        add('Footprint: '+code(bm['Footprint'] or 'not specified')+'. Supplier: '+code(bm['Supplier'] or 'not specified')+'. Supplier part: '+code(bm['Supplier Part'] or 'not specified')+'.')
        add()
        add('Schematic source: '+code(b['stem']+'.epru')+' line '+str(c['source_line'])+', component '+code(c['id'])+', symbol '+code(c['symbol_id'])+'.')
        add()
        if c['attrs'].get('Add into BOM')=='no':add('Population conflict: schematic `Add into BOM = no`; present in supplied BOM.');add()
        if b['board']=='PULSER' and c['ref'] in {f'R{r}' for r in range(17,65)}:add('Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.');add()
        rows=[]
        for p in sorted(c['pins'],key=lambda p:nat(p['number'])):
            evidence='NEAR' if p['near_wire_hits'] else 'EXACT' if p['wire_hits'] else 'NONE'
            rows.append([code(p['number']),code(p['name']),code(p['net']) if p['status']!='unconnected' else '—',code(p['saved_net']) if p['saved_net']!=p['net'] else 'same',p['status'].upper(),evidence])
        tab(['Pin','Source pin name','Primary net ID','Saved net','Status','Contact'],rows)

add('## 5. Complete net-to-endpoint index');add()
add('The records below are JSON Lines: one complete JSON object per line. `endpoints` lists every component terminal on the primary net. `aliases` contains source net labels without the board prefix. `saved_net_ids` lists the pre-bridge schematic nets merged into this primary net; the component tables identify each pin’s original membership. `bridged_components`, when present, lists owner-confirmed closed gaps. `wire_ids` and `label_ids` are source record IDs in the board’s `.epru` SCH_PAGE section. `near_pins` and `near_labels` identify accepted tolerance-dependent contacts. Unconnected terminals appear in Sections 4 and 6 and are not encoded as a shared net. Unnamed nets with only one attached terminal remain listed.');add()
for b in BOARDS:
    add('### '+b['board']+' net records');add();add('```jsonl')
    for g in b['nets']:
        if not g['pins'] or g['pins'][0]['status']=='unconnected':continue
        obj={'net':g['id'],'aliases':g['aliases'],'saved_net_ids':g['saved_net_ids'],'endpoints':[p['endpoint'] for p in g['pins']],'wire_ids':sorted(g['wires']),'label_ids':sorted(l['id'] for l in g['labels']),'near_pins':[p['endpoint'] for p in g['pins'] if p['near_wire_hits']],'near_labels':[l['id'] for l in g['labels'] if l['near_wire_hits']]}
        if b['board']=='PULSER' and len(g['saved_net_ids'])>1:obj['physical_override']='Owner-confirmed leaf mux solder gaps closed';obj['bridged_components']=[f'PULSER.R{r}' for m,label,lo,hi in BRIDGES if g['id']=='PULSER:'+label for r in range(lo,hi+1)]
        add(j(obj))
    add('```');add()
add('## 6. Unconnected and single-terminal inventory');add()
add('These inventories are exhaustive under the 0.25-unit reconstruction. A comma-separated list identifies individual pins, not a numeric range. An unconnected pin with a source name such as DNC retains that name in its component table; no intent is inferred here.');add()
for b in BOARDS:
    add('### '+b['board']+' unconnected terminals');add()
    tab(['Component','Unconnected pin numbers'],[[code(b['board']+'.'+c['ref']),', '.join(code(p['number']) for p in sorted(c['pins'],key=lambda p:nat(p['number'])) if p['status']=='unconnected')] for c in b['components'] if any(p['status']=='unconnected' for p in c['pins'])])
    add('### '+b['board']+' single-terminal nets');add()
    tab(['Net','Only attached terminal'],[[code(g['id']),code(g['pins'][0]['endpoint'])] for g in b['nets'] if len(g['pins'])==1 and g['pins'][0]['status']=='single_pin_net'])
add('### Wire without a terminal');add()
add('AFE wire group `4128d3e200c40422` has no attached component terminals or labels under the matching rule. It does not contribute an electrical connection between any listed parts.');add()

add('## 7. Source annotations');add()
add('The following are literal drawing TEXT records. They are source annotations, not executable instructions, proof of a physical short, or substitutions for the pin tables. Decorative title-block metadata is omitted.');add()
for b in BOARDS:
    add('### '+b['board']);add()
    for t in b['texts']:add('- Source text '+code(t.get('value',''))+' at ('+str(round(t['x'],6))+', '+str(round(t['y'],6))+'), record '+code(t['id'])+'.')
    add()
add('## 8. Coordinate-contact audit');add()
add('All distances are in the source schematic coordinate system, not millimetres. Each row identifies a contact greater than 0.0001 and no greater than 0.25 units that was accepted by the reconstruction. Exact source positions, closest active wire IDs, and distances are retained for native-editor follow-up. The four 0.31496063-unit cases in Section 2 were not accepted.');add()
for b in BOARDS:
    add('### '+b['board']+' pin-to-wire near contacts');add()
    rows=[]
    for c in b['components']:
        for p in sorted(c['pins'],key=lambda p:nat(p['number'])):
            for h in p['near_wire_hits']:rows.append([code(p['endpoint']),code(p['net']),f"{p['xy'][0]:.8f}, {p['xy'][1]:.8f}",code(h['wire_id']),f"{h['distance']:.8f}"])
    tab(['Endpoint','Assigned net','Pin position x, y','Wire ID','Offset'],rows)
    add('### '+b['board']+' label-to-wire near contacts');add()
    rows=[]
    for g in b['nets']:
        for l in g['labels']:
            for h in l['near_wire_hits']:rows.append([code(l['name']),code(l['id']),code(g['id']),f"{l['xy'][0]:.8f}, {l['xy'][1]:.8f}",code(h['wire_id']),f"{h['distance']:.8f}"])
    tab(['Label','Label component ID','Assigned net','Port position x, y','Wire ID','Offset'],rows)
add('## 9. Extraction rules and validation');add()
add('1. Read the two `.epro2` ZIP archives without modifying the sources. Parse every `.epru` record and identify SCH_PAGE component, attribute, wire, and line records plus the referenced DEVICE and SYMBOL records. Records with no body are excluded. Each archive contains one schematic and one page.');
add('2. Resolve each component’s selected symbol part and all of its PIN records. Apply source pin attributes and any instance pin overrides. Rotate counterclockwise in the schematic coordinate system, apply horizontal mirroring after rotation, and translate to the component position. The official [EasyEDA component-format reference](https://prodocs.easyeda.com/en/format/schematic/component/) describes the transform order and pin-attribute overrides.');
add('3. Treat LINE records sharing an active WIRE parent as one wire group. Retain the group’s electrical identity even when described by multiple segments. Use endpoint-on-segment contact to join distinct groups; do not join bare interior crossings. No distinct active WIRE groups required a geometric join at the strict tolerance in these files.');
add('4. Match pins and port anchors to active wire segments with a 0.25-unit distance limit; match coincident pin/port points at 0.0001 units. Merge exact, case-sensitive global-net and port names only within the same board. WIRE NET properties in the supplied records are empty; names are carried by the placed label/port symbols. The [EasyEDA pin-format reference](https://prodocs.easyeda.com/en/format/schematic/pin/) identifies pin coordinates as the external connection endpoint.');
add('5. Exclude LINE records whose WIRE parent is absent from the active schematic record set: 577 pulser segments and 516 AFE segments. They are retained in the source archives but do not establish active connections here. Exclude title-block artwork and non-electrical drawing records from the component inventory. Do not use cached thumbnail artwork as an authoritative replacement for active records.');
add('6. Expand each BOM designator list, require unique references, and check each row quantity against its list. Compare schematic and BOM reference sets exactly. Compare effective schematic Value, Manufacturer Part, and Supplier Part against the supplied BOM: no differences in those fields were found; the population flags described in Section 2 remain a separate discrepancy.');
add('7. Require each symbol terminal to occur once in its component pin table and either once in the net index or once in the unconnected inventory. Check endpoint uniqueness, BOM coverage, and exact agreement between the two representations. Include extra numbered symbol terminals and exposed pads rather than silently dropping them to match a part-name pin count.');
add('8. Compare reconstruction at 0.25 and 0.5 units. AFE net memberships are unchanged; the only pulser changes are the four ground candidates documented in Section 2. Native-editor connectivity was not exported or verified. EasyEDA supports [exporting its native netlist](https://prodocs.easyeda.com/en/schematic/export-netlist/) for a subsequent authoritative comparison.');
add('9. Apply the owner-confirmed physical override by shorting pins 1 and 2 of each of R17–R64, merging its saved nets into the appropriate leaf input net. Verify 48 bridges, 16 COM terminals per leaf on its assigned common node, and preservation of three separate input-bank nets. Preserve saved net IDs for reconstruction of the original schematic.');
add()
add('### Validation totals');add()
tab(['Check','PULSER','AFE'],[
    ['BOM rows',len(BOARDS[0]['bom_rows']),len(BOARDS[1]['bom_rows'])],
    ['Matched component references',116,111],
    ['Symbol terminals',565,614],
    ['Active WIRE groups',291,180],
    ['Active wire LINE segments',853,791],
    ['Named port / global-net instances',218,160],
    ['Pins with accepted near-wire contacts',39,78],
    ['Labels with accepted near-wire contacts',10,12],
    ['BOM-only / schematic-only references','0 / 0','0 / 0'],
])

OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
# Verify the final artifact, not only the in-memory graph.
text=OUT.read_text(encoding='utf-8')
parts=re.findall(r'^#### (PULSER|AFE)\.([^ ]+) —',text,re.M)
assert len(parts)==227 and len(set(parts))==227
net_records=[json.loads(line) for line in text.splitlines() if line.startswith('{"net":')]
net_endpoints=[e for g in net_records for e in g['endpoints']]
assert len(net_endpoints)==len(set(net_endpoints))
allpins=[p for b in BOARDS for c in b['components'] for p in c['pins']]
assert len(allpins)==1179 and len({p['endpoint'] for p in allpins})==1179
assert set(net_endpoints)=={p['endpoint'] for p in allpins if p['status']!='unconnected'}
expected={p['endpoint']:p['net'] for p in allpins if p['status']!='unconnected'}
assert all(expected[e]==g['net'] for g in net_records for e in g['endpoints'])
assert len(re.findall(r'^\| `[^`]+` \| `[^`]*` \| (?:`[^`]+`|—) \| (?:`[^`]+`|same) \| (?:CONNECTED|SINGLE_PIN_NET|UNCONNECTED) \| (?:EXACT|NEAR|NONE) \|$',text,re.M))==1179
for mux,label,lo,hi in BRIDGES:
    b=BOARDS[0]
    assert {p['net'] for p in co(b,mux)['pins'] if p['name'].startswith('COM')}=={'PULSER:'+label}
    assert all({p['net'] for p in co(b,f'R{r}')['pins']}=={'PULSER:'+label} for r in range(lo,hi+1))
assert len(net_records)==184
print(json.dumps({'output':str(OUT),'bytes':OUT.stat().st_size,'lines':len(lines),'components':len(parts),'pins':len(allpins),'net_records':len(net_records),'net_endpoints':len(net_endpoints),'unconnected_pins':sum(p['status']=='unconnected' for p in allpins),'validation':'passed'},indent=2))
