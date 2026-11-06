"""Render real inference requests, GPU KV WRITE events and host NIC counters."""
import argparse,json,re,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();root=a.directory
manifest=json.loads((root/'manifest.json').read_text());requests=json.loads((root/'requests.json').read_text());origin=manifest['start_wall_ns']
best=min(manifest['clock_probes'],key=lambda x:x['offset_max_ns']-x['offset_min_ns']);offset=(best['offset_max_ns']+best['offset_min_ns'])/2
fig,axes=plt.subplots(4,1,figsize=(13,10),sharex=True)
summary=dict(scope=manifest['scope'],status=manifest['status'],requests=len(requests),pd_requests=sum(r['label'].startswith(('pd-','concurrent-')) for r in requests),comparisons=[],transfers=[],clock_offset_ms=offset/1e6,clock_bound_ms=(best['offset_max_ns']-best['offset_min_ns'])/2e6)
for side,ax in [('local',axes[0]),('remote',axes[1])]:
 rows=[json.loads(l) for l in (root/(side+'-nics.jsonl')).read_text().splitlines()];samples=[r for r in rows if r['type']=='sample']
 for nic in [f'mlx5_bond_{i}' for i in range(8)]:
  for direction in ['rcv','xmit']:
   key=f'{nic}/1/counters/port_{direction}_data';points=[]
   for prev,cur in zip(samples,samples[1:]):
    if key not in cur['counters'] or key not in prev['counters']:continue
    dt=(cur['mono_ns']-prev['mono_ns'])/1e9;delta=cur['counters'][key]-prev['counters'][key]
    if dt>0 and delta>=0:points.append(((cur['wall_ns']-origin-(offset if side=='remote' else 0))/1e9,delta*4/dt/1e9))
   if points and max(y for _,y in points)>.01:ax.plot(*zip(*points),label=f'{nic} {direction}',linewidth=.8,linestyle='-' if direction=='rcv' else '--')
 ax.legend(fontsize=7,ncol=3);ax.set_ylabel(f'{side} NIC\nGB/s (sample avg)');ax.grid(alpha=.2)
for path in (root/'prefill-trace').glob('*.jsonl'):
 rows=[json.loads(l) for l in path.read_text().splitlines()];starts={}
 for r in rows:
  if r['event']=='call_start':starts[r['transfer_id']]=r
  elif r['event']=='call_end':
   s=starts[r['transfer_id']];wall=s['wall_ns']-offset
   if origin <= wall <= manifest['end_wall_ns']:
    summary['transfers'].append(dict(pid=s['pid'],transfer_id=s['transfer_id'],bytes=s['bytes'],descriptors=s['descriptors'],operation=s['operation'],duration_ms=r['duration_ns']/1e6,rc=r['rc'],t_s=(wall-origin)/1e9))
for t in summary['transfers']:
 axes[2].scatter(t['t_s'],t['bytes']/2**20,c='tab:purple',s=25)
axes[2].set_ylabel('GPU KV WRITE\nMiB / TE call');axes[2].grid(alpha=.2)
for kind in ['baseline','pd','concurrent']:
 points=[((r['start_wall_ns']-origin)/1e9,(r['end_wall_ns']-r['start_wall_ns'])/1e6) for r in requests if r['label'].startswith(kind)]
 if points:axes[3].scatter(*zip(*points),label=kind,s=18)
axes[3].set_ylabel('HTTP full response\nlatency (ms)');axes[3].legend();axes[3].grid(alpha=.2);axes[3].set_xlabel('Seconds since validation start (remote wall-clock offset estimated)')
fig.suptitle('vLLM + Mooncake GPU KV transfer: decoder requests KV, prefiller performs RDMA WRITE\nDiagnostic capture; detailed logging and batch-invariant execution enabled',fontsize=11)
fig.tight_layout(rect=[0,0,1,.94]);fig.savefig(root/'timeline.png',dpi=160);fig.savefig(root/'timeline.pdf')
if summary['transfers']:
 first=min(t['t_s'] for t in summary['transfers'])-1
 for ax in axes:ax.set_xlim(first,(manifest['end_wall_ns']-origin)/1e9)
 recent=[(r['end_wall_ns']-r['start_wall_ns'])/1e6 for r in requests if (r['start_wall_ns']-origin)/1e9>=first]
 if recent:axes[3].set_ylim(0,max(recent)*1.15)
 fig.savefig(root/'timeline-detail.png',dpi=160)
plt.close(fig)
for repeat in [1,128,512]:
 pair=[r for r in requests if r['label'] in [f'baseline-{repeat}',f'pd-{repeat}']]
 if len(pair)==2:summary['comparisons'].append(dict(prompt_tokens=pair[0]['response']['usage']['prompt_tokens'],exact_text_match=pair[0]['response']['choices'][0]['text']==pair[1]['response']['choices'][0]['text']))
summary['total_KV_bytes']=sum(t['bytes'] for t in summary['transfers']);summary['all_transfer_calls_succeeded']=all(t['rc']==0 for t in summary['transfers'])
log=(root/'prefill.log').read_text();summary['gpu_affinity_examples']=[l for l in log.splitlines() if 'source_location=cuda:0, target_location=cuda:0' in l][-3:]
(root/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k not in ['transfers','gpu_affinity_examples']},indent=2))
