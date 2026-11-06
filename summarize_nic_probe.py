import collections, json, re
from pathlib import Path
root=Path('experiments/nic-selection')
summary={}
for p in sorted(root.glob('*-single.json'))+sorted(root.glob('*-batch.json')):
    d=json.loads(p.read_text()); name=p.stem
    logs=(root/f'{name}.log').read_text()
    pairs=collections.defaultdict(lambda: {'slices':0,'bytes':0,'retry_slices':0})
    for line in logs.splitlines():
        m=re.search(r'local_device_name=([^,]+), peer_device_name=([^,]+).*length=(\d+)',line)
        if m:
            v=pairs[f'{m[1]} -> {m[2]}'];v['slices']+=1;v['bytes']+=int(m[3]);v['retry_slices']+=int('retry_cnt=' in line)
    def delta(before,after):
        result={}
        for dev, vals in after.items():
            row={k: v-before.get(dev,{}).get(k,v) for k,v in vals.items()}
            result[dev]=row
        return result
    r=json.loads((root/f'{name}-remote-counters.json').read_text())
    summary[name]=dict(seconds=d['seconds'], verified=d['verified'], pairs=dict(pairs),local_delta=delta(d['before'],d['after']),remote_delta=delta(r['before'],r['after']), error_lines=[l for l in logs.splitlines() if 'error' in l.lower() or 'failed' in l.lower()][:40])
(root/'summary.json').write_text(json.dumps(summary,indent=2))
for name,d in summary.items():
    print(name, d['seconds'])
    print('pairs',d['pairs'])
    for side in ['local','remote']:
        print(side, {dev:{k:v for k,v in row.items() if k in ['port_xmit_data','port_rcv_data','port_rcv_errors','port_xmit_discards']} for dev,row in d[f'{side}_delta'].items() if any(row.get(k,0) for k in ['port_xmit_data','port_rcv_data'])})
