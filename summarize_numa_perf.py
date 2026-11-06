import collections, json, re, statistics
from pathlib import Path
out={}
for folder in ['numa-performance','numa-performance-warm']:
 root=Path('experiments')/folder
 cases={}
 for p in sorted(root.glob('*-performance-*.json')):
  if 'remote-counters' in p.name: continue
  d=json.loads(p.read_text()); times=d['seconds']; med=statistics.median(times)
  cases[p.stem]={'median_ms':med*1000,'min_ms':min(times)*1000,'max_ms':max(times)*1000,'median_GBps':d['bytes_per_iteration']/med/1e9,'iterations':len(times),'warmup':d['warmup'],'verified':d['verified'],'local_rx_GiB':{nic:(vals.get('port_rcv_data',0)-d['before'][nic].get('port_rcv_data',0))*4/2**30 for nic,vals in d['after'].items()}}
 paths={}
 for p in root.glob('*-diagnostic-*.log'):
  counts=collections.Counter()
  for line in p.read_text().splitlines():
   m=re.search(r'source_location=([^,]+), target_location=([^,]+), local_device_name=([^,]+), peer_device_name=([^,]+).*length=(\d+)',line)
   if m: counts[' | '.join(m.group(i) for i in range(1,5))]+=int(m[5])
  paths[p.stem]=dict(counts)
 out[folder]={'performance':cases,'diagnostic_bytes_by_location_and_nic':paths}
Path('experiments/numa-performance/summary.json').write_text(json.dumps(out,indent=2))
for folder,v in out.items():
 print(folder)
 for name,d in v['performance'].items():print(name,round(d['median_ms'],3),round(d['median_GBps'],2),round(d['max_ms'],3))
