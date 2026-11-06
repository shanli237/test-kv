"""Capture baseline, single/batch/parallel READ phases and recovery without overwriting runs."""
import argparse
import datetime
import json
import os
import shlex
import signal
import subprocess as sp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT/'.venv/bin/python')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--remote', help='SSH host, e.g. 11.163.39.110; omit for local smoke test')
    p.add_argument('--local-host', default='11.163.39.114')
    p.add_argument('--remote-host', default='11.163.39.110')
    p.add_argument('--repeats', type=int, default=24)
    p.add_argument('--mib', type=int, default=256)
    a = p.parse_args()
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT/'experiments/telemetry'/run_id
    out.mkdir(parents=True)
    remote_dir = str(out)
    manifest = dict(run_id=run_id, scope='cross-host' if a.remote else 'same-host',
                    config=vars(a), start_wall_ns=time.time_ns(), clock_probes=[])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    jobs=[]
    def ssh(command):
        return sp.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',a.remote,command],text=True,timeout=30)
    def launch(args, name, remote=False):
        log=(out/(name+'.log')).open('w')
        pidfile=remote_dir+'/'+name+'.pid'
        if remote:
            command=f'cd {shlex.quote(str(ROOT))} && echo $$ > {shlex.quote(pidfile)} && exec '+shlex.join(args)
            command=['ssh','-o','BatchMode=yes',a.remote,command]
        else: command=args
        proc=sp.Popen(command,cwd=ROOT,stdout=log,stderr=sp.STDOUT)
        jobs.append((proc,log,remote,pidfile))
        for _ in range(600):
            if 'READY' in (out/(name+'.log')).read_text():return
            if proc.poll() is not None: raise RuntimeError(f'{name} exited: inspect {out}')
            time.sleep(.2)
        raise TimeoutError(name)
    env=['env','MC_TE_FILTERS=mlx5_bond_0','MC_LOG_RDMA_SLICE_AFFINITY=0','GLOG_v=0']
    try:
        if a.remote:
            ssh('mkdir -p '+shlex.quote(remote_dir))
            # Persistent channel excludes SSH startup from each clock probe.
            clock_code = "import sys,time; print('READY',flush=True); [(print(time.time_ns(),flush=True)) for line in sys.stdin]"
            with sp.Popen(['ssh','-o','BatchMode=yes',a.remote,shlex.join([PYTHON,'-u','-c',clock_code])], stdin=sp.PIPE,stdout=sp.PIPE,text=True) as clock:
                if clock.stdout.readline().strip() != 'READY':
                    raise RuntimeError('clock probe unavailable')
                for _ in range(5):
                    before=time.time_ns()
                    clock.stdin.write('probe\n');clock.stdin.flush()
                    stamp=int(clock.stdout.readline().strip())
                    after=time.time_ns()
                    manifest['clock_probes'].append(dict(local_before_ns=before,remote_ns=stamp,local_after_ns=after,offset_min_ns=stamp-after,offset_max_ns=stamp-before))
                clock.stdin.close()
                clock.wait(timeout=10)
        target_info=remote_dir+'/target.json'
        launch(env+[PYTHON,'nic_probe.py','target','--host',a.remote_host if a.remote else a.local_host,'--device','mlx5_bond_0','--numa','0','--mib',str(a.mib),'--info',target_info],'target',bool(a.remote))
        if a.remote:
            sp.run(['scp',f'{a.remote}:{target_info}',str(out/'target.json')],check=True,timeout=30)
        launch([PYTHON,'monitoring/sample_nics.py','--output',str(out/'local-nics.jsonl')],'local-sampler')
        if a.remote:
            launch([PYTHON,'monitoring/sample_nics.py','--output',remote_dir+'/remote-nics.jsonl'],'remote-sampler',True)
        phases=[]
        def mark(name):
            phases.append(dict(phase=name,mono_ns=time.monotonic_ns(),wall_ns=time.time_ns()))
            (out/'phases.json').write_text(json.dumps(phases,indent=2))
        mark('baseline');time.sleep(2)
        for mode in ['single','batch','parallel']:
            mark(mode)
            args=env+[PYTHON,'nic_probe.py','pull','--host',a.local_host,'--device','mlx5_bond_0','--numa','0','--mib',str(a.mib),'--info',str(out/'target.json'),'--mode',mode,'--warmup','2','--repeats',str(a.repeats),'--events',str(out/(mode+'-events.jsonl')),'--output',str(out/(mode+'-result.json'))]
            with (out/(mode+'-pull.log')).open('w') as log:
                sp.run(args,cwd=ROOT,stdout=log,stderr=sp.STDOUT,check=True,timeout=180)
            mark(mode+'-recovery');time.sleep(1)
        mark('end')
        manifest['status']='passed'
    except BaseException as exc:
        manifest['status']='failed'
        manifest['error']=repr(exc)
        raise
    finally:
        cleanup=[]
        for proc,log,is_remote,pidfile in reversed(jobs):
            try:
                if proc.poll() is None:
                    if is_remote: ssh('kill -TERM "$(cat '+shlex.quote(pidfile)+')"')
                    else: proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=20)
            except Exception as exc: cleanup.append(repr(exc))
            log.close()
        if a.remote and (out/'remote-sampler.log').exists():
            sp.run(['scp',f'{a.remote}:{remote_dir}/remote-nics.jsonl',str(out/'remote-nics.jsonl')],timeout=30,check=False)
        manifest['cleanup_errors']=cleanup
        manifest['end_wall_ns']=time.time_ns()
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print(out,flush=True)
    sp.run([PYTHON,'monitoring/render_capture.py',str(out)],cwd=ROOT,check=True)

if __name__=='__main__':main()
