"""Local bond_0 fixed; remote one vs four NICs, ABBA order."""
import json, os, subprocess as sp, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments/remote-nic-control'
REMOTE='11.163.39.110'
WORK='/workspace/FuseLink/testvllm'
PYTHON=str(ROOT/'.venv/bin/python')
def remote(cmd):
    return sp.check_output(['ssh','-o','BatchMode=yes',REMOTE,cmd],text=True,timeout=30)
def snap():
    return json.loads(remote(f'cd {WORK} && .venv/bin/python nic_probe.py counters'))
procs=[]
try:
    for policy in ['one','four']:
        filters='mlx5_bond_0' if policy=='one' else ','.join(f'mlx5_bond_{i}' for i in range(4))
        info=f'probe-remote-{policy}.json'
        log=(OUT/f'{policy}-target.log').open('w')
        cmd=f'cd {WORK} && echo $$ > probe-remote-{policy}.pid && exec env MC_TE_FILTERS={filters} GLOG_v=0 MC_LOG_RDMA_SLICE_AFFINITY=0 .venv/bin/python nic_probe.py target --host {REMOTE} --info {info} --numa 0 --mib 512'
        if policy=='one': cmd+=' --device mlx5_bond_0'
        proc=sp.Popen(['ssh',REMOTE,cmd],stdout=log,stderr=sp.STDOUT)
        procs.append((policy,proc,log))
        for _ in range(30):
            if 'READY' in (OUT/f'{policy}-target.log').read_text(): break
            if proc.poll() is not None: raise RuntimeError('target exited')
            time.sleep(1)
        else: raise TimeoutError('target readiness')
        sp.run(['scp',f'{REMOTE}:{WORK}/{info}',str(OUT/info)],check=True,timeout=20)
    bg={'remote_before':snap(),'local_before':json.loads(sp.check_output([PYTHON,'nic_probe.py','counters']))}
    time.sleep(2)
    bg.update(remote_after=snap(),local_after=json.loads(sp.check_output([PYTHON,'nic_probe.py','counters'])))
    (OUT/'background.json').write_text(json.dumps(bg,indent=2))
    cases=[('diagnostic',i,p,m) for i,p in enumerate(['one','four']) for m in ['single','batch']]
    cases += [('performance',i,p,m) for i,p in enumerate(['one','four','four','one']) for m in (['single','batch'] if i%2==0 else ['batch','single'])]
    for phase,i,policy,mode in cases:
        name=f'{phase}-{i}-{policy}-{mode}'
        env=dict(os.environ,MC_TE_FILTERS='mlx5_bond_0',GLOG_v=('1' if phase=='diagnostic' else '0'),MC_LOG_RDMA_SLICE_AFFINITY=('1' if phase=='diagnostic' else '0'))
        args=[PYTHON,'nic_probe.py','pull','--host','11.163.39.114','--device','mlx5_bond_0','--numa','0','--mib','512','--mode',mode,'--info',str(OUT/f'probe-remote-{policy}.json'),'--output',str(OUT/f'{name}.json'),'--warmup',('0' if phase=='diagnostic' else '8'),'--repeats',('1' if phase=='diagnostic' else '20')]
        before=snap()
        with (OUT/f'{name}.log').open('w') as log:
            sp.run(args,env=env,stdout=log,stderr=sp.STDOUT,check=True,timeout=180)
        (OUT/f'{name}-remote-counters.json').write_text(json.dumps(dict(before=before,after=snap()),indent=2))
        print('PASS',name,flush=True)
finally:
    for policy,proc,log in procs:
        remote(f'cd {WORK} && kill -TERM "$(cat probe-remote-{policy}.pid)"')
        proc.wait(timeout=20);log.close()
