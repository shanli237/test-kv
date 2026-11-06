"""Validate independent capture invariants after an actual run."""
import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
manifest=json.loads((root/'manifest.json').read_text())
assert manifest['status']=='passed'
assert not manifest['cleanup_errors']
for side in ['local','remote'] if manifest['scope']=='cross-host' else ['local']:
    records=[json.loads(x) for x in (root/(side+'-nics.jsonl')).read_text().splitlines()]
    assert records[0]['type']=='metadata' and records[-1]['type']=='stop'
    samples=[x for x in records if x['type']=='sample']
    assert len(samples)>10
    assert all(b['mono_ns']>a['mono_ns'] for a,b in zip(samples,samples[1:]))
    assert all(x['end_mono_ns']>=x['mono_ns'] and not x['errors'] for x in samples)
    intervals=[(b['mono_ns']-a['mono_ns'])/1e9 for a,b in zip(samples,samples[1:])]
    print(side,'samples',len(samples),'mean_interval_s',sum(intervals)/len(intervals))
total=0
for mode in ['single','batch','parallel']:
    result=json.loads((root/(mode+'-result.json')).read_text())
    assert result['verified']
    events=[json.loads(x) for x in (root/(mode+'-events.jsonl')).read_text().splitlines()]
    starts={};ends={};verified={}
    for e in events:
        if e['event']=='call_start':
            assert e['transfer_id'] not in starts
            starts[e['transfer_id']]=e
        elif e['event']=='call_end':
            assert e['transfer_id'] not in ends
            ends[e['transfer_id']]=e
        else:
            assert e['event']=='verified'
            verified[e['iteration']]=e
    assert starts.keys()==ends.keys()
    assert len(verified)==result['repeats']+result['warmup']
    for key,start in starts.items():
        end=ends[key]
        assert end['rc']==0 and end['mono_ns']>=start['mono_ns']
        assert 0<=end['duration_ns']<=end['mono_ns']-start['mono_ns']
    for iteration in verified:
        calls=[s for s in starts.values() if s['iteration']==iteration]
        assert len(calls)==(4 if mode=='parallel' else 1)
        assert sum(s['bytes'] for s in calls)==result['bytes_per_iteration']
        assert verified[iteration]['mono_ns']>=max(ends[s['transfer_id']]['mono_ns'] for s in calls)
        total+=result['bytes_per_iteration']
    print(mode,'calls',len(starts),'verified_iterations',len(verified))
print('PASS total_verified_GiB',total/2**30)
