"""Offline feasibility calculations for this board's shared pulser/mux topology.

No host, USB, serial port, uploader or hardware-command modules are imported.
Masks are design examples, NOT commands accepted by the current firmware.
"""
import argparse
import json
import math
from pathlib import Path
import re

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
RTL=ROOT/'usb3-tester.srcs/sources_1/new/tx_sequencer.v'

def mapping():
    source=RTL.read_text()
    found=re.findall(r"6'd(\d+)\s*:\s*mux_code\s*=\s*\{2'd(\d+),\s*4'd(\d+)",source)
    result={int(e):(int(b),int(c)) for e,b,c in found}
    if set(result)!=set(range(48)) or len(set(result.values()))!=48:
        raise ValueError('The actual RTL must contain 48 distinct physical element mappings')
    return result

def word(elements,table):
    if not elements or len(elements)!=len(set(elements)) or any(e not in table for e in elements):
        raise ValueError('Invalid element selection')
    words=[0,0,0,0]  # ROOT, BR1, BR2, BR3
    for e in elements:
        branch,channel=table[e]
        words[0]|=1<<[5,7,11][branch]
        words[branch+1]|=1<<channel
    return sum(v<<(16*i) for i,v in enumerate(words))

def decode(value,table):
    root=value&0xffff
    if root & ~sum(1<<s for s in [5,7,11]):raise ValueError('Unused root switches selected')
    active=[]
    for e,(b,c) in table.items():
        if root&(1<<[5,7,11][b]) and value&(1<<(16*(b+1)+c)):active.append(e)
    return active

def bench_pair(tx,rx,table):
    if (len(tx)!=2 or abs(tx[0]-tx[1])!=1 or table[tx[0]][0]!=table[tx[1]][0]
            or rx not in tx or any(e in [25,46] for e in tx)):
        raise ValueError('Initial proposal allows only two adjacent same-bank elements and one RX member, excluding 25/46')
    a,b=word(tx,table),word([rx],table)
    assert decode(a,table)==sorted(tx)
    assert decode(b,table)==[rx]
    assert b&a==b
    return {'tx_elements':tx,'rx_element':rx,'tx_chain_hex':f'{a:016x}','rx_chain_hex':f'{b:016x}',
            'state':'Design proposal only; current firmware rejects the two-element word'}

def array_factor(n,frequency_mhz,angles_deg,pitch_mm=.3375,c_m_s=1540):
    x=(np.arange(n)-(n-1)/2)*pitch_mm*1e-3
    k=2*np.pi*frequency_mhz*1e6/c_m_s
    return np.abs(np.exp(-1j*k*np.sin(np.radians(angles_deg))[:,None]*x).sum(axis=1))

def results():
    table=mapping()
    for i in range(48):assert decode(word([i],table),table)==[i]
    pair=bench_pair([20,21],20,table)
    angles=[0,10,20,30]
    patterns=[]
    for n in [1,2,4]:
        for f in [2,3,3.5,4,4.7]:
            af=array_factor(n,f,np.array(angles))
            patterns.append({'tx_count':n,'frequency_mhz':f,'angles_deg':angles,
                             'pressure_gain_db_vs_single_at_same_element_voltage':(20*np.log10(np.maximum(af,1e-12))).tolist()})
    # Current 100 MHz logic, 10 MHz chain; keep the current 5 us settle setting.
    burst=1.04;inhibit=4.5;shift=64/10;latch=.02+.05;settle=5
    earliest=burst+inhibit+shift+latch+settle
    preloaded=burst+inhibit+latch+settle
    return {'model':'Ideal equal-voltage point-element far field; not a measured SNR or acoustic output prediction',
            'limits':['Omits loading, element directivity, attenuation, near-field effects and acoustic coupling',
                      'All selected TX elements share polarity and timing on this single pulser',
                      'No independent per-element receive traces can be inferred from a simultaneous TX sum'],
            'pitch_mm':.3375,'c_m_s':1540,'example_pair':pair,'patterns':patterns,
            'same_bank_adjacent_pairs':[[i,i+1] for i in range(47) if table[i][0]==table[i+1][0] and i not in [25,46] and i+1 not in [25,46]],
            'rx_change_timing_us':{'burst':burst,'inhibit':inhibit,'chain_shift':shift,'latch_guards':latch,'settle':settle,
                                   'post_tx_shift_budget_before_extra_margin':earliest,
                                   'preloaded_rx_budget_before_extra_margin':preloaded,
                                   'current_rx_start':16,'preloaded_margin_before_extra_fsm_and_analog_recovery':16-preloaded,
                                   'fallback_bench_rx_start_if_shifting_after_tx':24,
                                   'preload_requirement':'Latch TX, preload RX with LE high before firing, allow a quiet settle, then latch RX only after HV inhibit expires'},
            'time_and_energy_tradeoffs':{'48_shot_aperture_ms':26.64,'24_shots_same_period_ms':13.32,
                '48_by_48_full_matrix_same_period_ms':26.64*48,
                'four_repeats_ideal_uncorrelated_noise_gain_db':10*math.log10(4),
                'fourfold_chirp_energy_ideal_matched_filter_gain_db':10*math.log10(4),
                'qualification':'Ideal gains require independent receiver noise, correct decoding and unchanged echo coherence; not validated here'}}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'bench_runs/transmit-options-20260909/model.json')
    args=p.parse_args();value=results()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,indent=2),encoding='utf-8')
    print(json.dumps({'example_pair':value['example_pair'],'rx_change_timing_us':value['rx_change_timing_us'],
                      'pair_3p5_mhz':next(v for v in value['patterns'] if v['tx_count']==2 and v['frequency_mhz']==3.5)},indent=2))
