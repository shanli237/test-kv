"""Run the four controlled cases against the configured lab peer."""
import json, os, subprocess as sp, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'experiments/nic-selection'
REMOTE = '11.163.39.110'
WORK = '/workspace/FuseLink/testvllm'
PYTHON = str(ROOT / '.venv/bin/python')
BONDS = ','.join(f'mlx5_bond_{i}' for i in range(8))
def remote(cmd):
    return sp.check_output(['ssh', '-o', 'BatchMode=yes', REMOTE, cmd], text=True, timeout=30)
def snap():
    return json.loads(remote(f'cd {WORK} && .venv/bin/python nic_probe.py counters'))
for policy in ['single-nic', 'multi-nic']:
    filters = 'mlx5_bond_0' if policy == 'single-nic' else BONDS
    device = 'mlx5_bond_0' if policy == 'single-nic' else ''
    info = f'probe-{policy}.json'
    remote(f'cd {WORK} && mkdir -p experiments/nic-selection')
    # Capture background traffic with no probe transfer for two seconds.
    bg = {'remote_before': snap()}
    bg['local_before'] = json.loads(sp.check_output([PYTHON,'nic_probe.py','counters']))
    time.sleep(2)
    bg['remote_after'] = snap()
    bg['local_after'] = json.loads(sp.check_output([PYTHON,'nic_probe.py','counters']))
    (OUT/f'{policy}-background.json').write_text(json.dumps(bg,indent=2))
    cmd = f'cd {WORK} && echo $$ > probe-{policy}.pid && exec env MC_TE_FILTERS={filters} MC_LOG_RDMA_SLICE_AFFINITY=1 GLOG_v=1 .venv/bin/python nic_probe.py target --host {REMOTE} --info {info}'
    if device: cmd += f' --device {device}'
    with (OUT/f'{policy}-target.log').open('w') as log:
        proc = sp.Popen(['ssh',REMOTE,cmd],stdout=log,stderr=sp.STDOUT)
        try:
            for _ in range(30):
                if 'READY' in (OUT/f'{policy}-target.log').read_text(): break
                if proc.poll() is not None: raise RuntimeError('target exited')
                time.sleep(1)
            else: raise TimeoutError('target readiness')
            sp.run(['scp',f'{REMOTE}:{WORK}/{info}',str(OUT/info)],check=True,timeout=20)
            for mode in ['single','batch']:
                name = f'{policy}-{mode}'
                before = snap()
                env = dict(os.environ, MC_TE_FILTERS=filters, MC_LOG_RDMA_SLICE_AFFINITY='1', GLOG_v='1')
                args=[PYTHON,'nic_probe.py','pull','--host','11.163.39.114','--info',str(OUT/info),'--mode',mode,'--output',str(OUT/f'{name}.json')]
                if device: args += ['--device',device]
                with (OUT/f'{name}.log').open('w') as out:
                    sp.run(args,env=env,stdout=out,stderr=sp.STDOUT,check=True,timeout=180)
                (OUT/f'{name}-remote-counters.json').write_text(json.dumps(dict(before=before,after=snap()),indent=2))
                print('PASS',name,flush=True)
        finally:
            remote(f'cd {WORK} && kill -TERM "$(cat probe-{policy}.pid)"')
            proc.wait(timeout=20)
