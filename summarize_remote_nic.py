import collections,json,re,statistics
from pathlib import Path
root=Path('experiments/remote-nic-control')
summary={'cases':{},'diagnostic':{}}
for p in sorted(root.glob('performance-*.json')):
 if 'remote-counters' in p.name: continue
 d=json.loads(p.read_text()); t=d['seconds'];median=statistics.median(t)
 r=json.loads(p.with_name(p.stem+'-remote-counters.json').read_text())
 counters={}
 for side,obj,key in [('local',d,'port_rcv_data'),('remote',r,'port_xmit_data')]:
  counters[side]={n:(v[key]-obj['before'][n][key])*4/2**30 for n,v in obj['after'].items() if key in v}
 summary['cases'][p.stem]=dict(median_ms=median*1000,min_ms=min(t)*1000,max_ms=max(t)*1000,GBps=d['bytes_per_iteration']/median/1e9,verified=d['verified'],counters_GiB=counters)
for p in root.glob('diagnostic-*.log'):
 pairs=collections.Counter()
 for line in p.read_text().splitlines():
  m=re.search(r'source_location=([^,]+), target_location=([^,]+), local_device_name=([^,]+), peer_device_name=([^,]+).*length=(\d+)',line)
  if m:pairs[' | '.join(m.group(i) for i in range(1,5))]+=int(m[5])
 summary['diagnostic'][p.stem]=dict(pairs)
(root/'summary.json').write_text(json.dumps(summary,indent=2))
for n,d in summary['cases'].items(): print(n,round(d['median_ms'],3),round(d['GBps'],2),round(d['max_ms'],3))
for n,d in summary['diagnostic'].items():print(n,d)
