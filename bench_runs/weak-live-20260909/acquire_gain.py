from study import *
if __name__=='__main__':
    for tgc in [1200,1400,1800,1600]:
        name=f'gain-{tgc}'
        path=capture(name,tgc=tgc)
        d=json.loads((path.parent/'capture.report.json').read_text())
        print('quality',name,'max ADC',max(e['peak_counts'] for e in d['elements']),
              'clipped elements',[(e['element'],round(e['clipped_fraction'],7)) for e in d['elements'] if e['clipped_fraction']],flush=True)
