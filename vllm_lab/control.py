"""Manage only the three lab services; prefill commands execute via SSH."""
import argparse,os,signal,subprocess as sp,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop','status']);p.add_argument('role',choices=['prefill','decode','proxy','all']);p.add_argument('--on-node',action='store_true');a=p.parse_args()
roles=['prefill','decode','proxy'] if a.role=='all' else [a.role]
if a.action=='stop':roles=roles[::-1]
for role in roles:
 if role=='prefill' and not a.on_node:
  sp.run(['ssh','11.163.39.110',f'cd {ROOT} && .venv-vllm/bin/python vllm_lab/control.py {a.action} prefill --on-node'],check=True);continue
 pidfile=ROOT/'vllm_lab/logs'/f'{role}.pid'
 pid=int(pidfile.read_text()) if pidfile.exists() else None
 def owned():
  if not pid:return False
  try:
   cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
   expected=b'mooncake_connector_proxy.py' if role=='proxy' else b'qwen-kv-lab'
   return expected in cmd and os.getpgid(pid)==pid
  except (OSError,ProcessLookupError):return False
 if a.action=='status':print(role,pid,'running' if owned() else 'stopped');continue
 if a.action=='stop':
  if owned():
   os.killpg(pid,signal.SIGTERM)
   for _ in range(100):
    if not owned():break
    time.sleep(.1)
   if owned():raise RuntimeError(f'{role} did not stop')
  print('stopped',role);continue
 if owned():print('already running',role,pid);continue
 if role=='proxy':cmd=[str(ROOT/'.venv-vllm/bin/python'),str(ROOT/'vllm_lab/vendor/mooncake_connector_proxy.py'),'--host','127.0.0.1','--port','18900','--prefill','http://11.163.39.110:18910','18998','--decode','http://11.163.39.114:18920']
 else:cmd=['bash',str(ROOT/'vllm_lab/serve.sh'),role]
 with (ROOT/'vllm_lab/logs'/f'{role}.log').open('a') as log:
  proc=sp.Popen(cmd,cwd=ROOT,stdout=log,stderr=sp.STDOUT,stdin=sp.DEVNULL,start_new_session=True)
 pidfile.write_text(str(proc.pid));print('started',role,proc.pid)
