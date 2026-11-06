"""Render standalone PNG and PDF, preserving raw metrics and timestamp bounds."""
import argparse
import csv
import json
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read_lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();root=a.directory
    manifest=json.loads((root/'manifest.json').read_text())
    phases=json.loads((root/'phases.json').read_text())
    origin=phases[0]['mono_ns'];wall_origin=phases[0]['wall_ns']
    summary=dict(scope=manifest['scope'],samplers={},calls={},limitations=[
        'Counters are host-wide; background traffic is not subtracted.',
        '100 ms averages miss short bursts. No NIC hardware queue occupancy is measured.',
        'In-flight tracks Python-to-TE API calls, including software work, not posted RDMA WRs.',
        'Batch is one API call containing many requests. Warmup calls are included.',
        'Workload is closed-loop with clear/verify gaps, not a steady saturation benchmark.',
        'No per-transfer automatic NIC choice trace or internal retry event instrumentation in this capture.',
        'Device/netdev inventory is evidence only; physical bond members and link utilization denominator remain unverified.' ])
    rates=[]
    for side in ['local','remote']:
        path=root/(side+'-nics.jsonl')
        if not path.exists():continue
        rows=read_lines(path);samples=[x for x in rows if x['type']=='sample']
        spans=[(x['end_mono_ns']-x['mono_ns'])/1e6 for x in samples]
        reset=[];changes={}
        last_counter={}
        for sample in samples:
            for key,value in sample["counters"].items():
                if key in last_counter:
                    delta=value-last_counter[key]
                    if delta < 0: reset.append(key)
                    else: changes[key]=changes.get(key,0)+delta
                last_counter[key]=value
        for prev,cur in zip(samples,samples[1:]):
            dt=(cur['mono_ns']-prev['mono_ns'])/1e9
            if dt<=0:continue
            for key,v in cur['counters'].items():
                if key not in prev['counters']:continue
                delta=v-prev['counters'][key]
                if delta<0:reset.append(key);continue
                if key.endswith('/counters/port_rcv_data') or key.endswith('/counters/port_xmit_data'):
                    t=(cur['mono_ns']-origin)/1e9 if side=='local' else (cur['wall_ns']-wall_origin)/1e9
                    rates.append(dict(side=side,t_s=t,nic=key.split('/')[0],direction='rx' if key.endswith('rcv_data') else 'tx',GBps=delta*4/dt/1e9))
        summary['samplers'][side]=dict(samples=len(samples),median_read_ms=statistics.median(spans),max_read_ms=max(spans),median_interval_ms=statistics.median([(b['mono_ns']-a['mono_ns'])/1e6 for a,b in zip(samples,samples[1:])]),interval_overruns=sum(v>rows[0]['interval']*1000 for v in spans),counter_resets=sorted(set(reset)),read_errors=sum(len(x['errors']) for x in samples),nonzero_counter_deltas={k:v for k,v in changes.items() if v},inventory=rows[0]['inventory'])
    # Remote wall alignment is approximate and its SSH-derived bound is stated explicitly.
    probes=manifest.get('clock_probes',[])
    offset=0;uncertainty=None
    if probes:
        best=min(probes,key=lambda x:x['offset_max_ns']-x['offset_min_ns'])
        offset=(best['offset_min_ns']+best['offset_max_ns'])/2/1e9
        uncertainty=(best['offset_max_ns']-best['offset_min_ns'])/2/1e6
        summary['remote_alignment']=dict(offset_estimate_ms=offset*1000,uncertainty_bound_ms=uncertainty,method='SSH wall-time bracket; not measured NTP/PTP synchronization; assumes stable clocks')
        for row in rates:
            if row['side']=='remote':row['t_s']-=offset
    events=[]
    for path in root.glob('*-events.jsonl'):events.extend(read_lines(path))
    events.sort(key=lambda x:x['mono_ns'])
    starts={};active={};inflight=[(0,0,0)];latencies=[]
    for event in events:
        t=(event['mono_ns']-origin)/1e9
        if event['event']=='call_start':
            # IDs are process-local; modes are sequential in this runner.
            key=(event['mode'],event['transfer_id'])
            starts[key]=event;active[key]=event['bytes']
            inflight.append((t,len(active),sum(active.values())/2**20))
        elif event['event']=='call_end':
            matches=[k for k in active if k[1]==event['transfer_id'] and (event.get('mode') is None or k[0]==event['mode'])]
            if len(matches)!=1:raise ValueError('unmatched/ambiguous call end')
            key=matches[0];start=starts[key];active.pop(key)
            if event['rc']!=0:raise ValueError(f'failed call: {event}')
            latencies.append((t,event['duration_ns']/1e6,start['mode'],start['iteration']<0))
            inflight.append((t,len(active),sum(active.values())/2**20))
    if active:raise ValueError('unfinished calls')
    for mode in ['single','batch','parallel']:
        times=[v for _,v,m,w in latencies if m==mode and not w]
        if times:
            summary['calls'][mode]=dict(measured_calls=len(times),median_API_ms=statistics.median(times),max_API_ms=max(times),verified_iterations=sum(e['event']=='verified' and e.get('mode')==mode for e in events))
    summary['peak_application_inflight_calls']=max(n for _,n,_ in inflight)
    summary['peak_application_inflight_MiB']=max(b for _,_,b in inflight)
    with (root/'rates.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['side','t_s','nic','direction','GBps']);writer.writeheader();writer.writerows(rates)
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    has_remote='remote' in summary['samplers']
    fig,axes=plt.subplots(5 if has_remote else 4,1,figsize=(13,12 if has_remote else 10),sharex=True)
    axidx=0
    for side in (['local','remote'] if has_remote else ['local']):
        ax=axes[axidx];axidx+=1
        for nic in sorted({r['nic'] for r in rates}):
            for direction in ['rx','tx']:
                selected=[r for r in rates if r['side']==side and r['nic']==nic and r['direction']==direction]
                if selected and max(r['GBps'] for r in selected)>.001:
                    ax.plot([r['t_s'] for r in selected],[r['GBps'] for r in selected],label=f'{nic} {direction}',linestyle='-' if direction=='rx' else '--',linewidth=1)
        ax.set_ylabel(f'{side} NIC\nGB/s (sample avg)');ax.legend(fontsize=7,ncol=3,loc='upper right')
    axes[axidx].step([t for t,_,_ in inflight],[n for _,n,_ in inflight],where='post');axes[axidx].set_ylabel('API calls\nin flight');axidx+=1
    axes[axidx].step([t for t,_,_ in inflight],[b for _,_,b in inflight],where='post');axes[axidx].set_ylabel('API bytes\nin flight (MiB)');axidx+=1
    for mode in ['single','batch','parallel']:
        points=[(t,ms) for t,ms,m,w in latencies if m==mode]
        if points:axes[axidx].scatter(*zip(*points),s=7,label=mode)
    axes[axidx].set_ylabel('API latency (ms)');axes[axidx].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
        for phase in phases:
            x=(phase['mono_ns']-origin)/1e9
            ax.axvline(x,color='gray',alpha=.3,linewidth=.7)
    for phase in phases:
        if phase['phase'] in ['baseline','single','batch','parallel']:
            axes[0].text((phase['mono_ns']-origin)/1e9,1.01,phase['phase'],transform=axes[0].get_xaxis_transform(),fontsize=8)
    axes[-1].set_xlabel('Seconds since local baseline start')
    title=f"Mooncake CPU READ telemetry ({manifest['scope']}); not a saturation benchmark"
    if uncertainty is not None:title+=f'\nRemote alignment uncertainty at least +/- {uncertainty:.1f} ms (SSH bracket)'
    fig.suptitle(title,fontsize=12);fig.tight_layout(rect=[0,0,1,.95])
    fig.savefig(root/'timeline.png',dpi=160);fig.savefig(root/'timeline.pdf');plt.close(fig)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['samplers','limitations']},indent=2))

if __name__=='__main__':main()
