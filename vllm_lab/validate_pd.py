"""Real-model PD validation, deterministic local-prefill control and two-sided NIC sampling."""
import concurrent.futures,datetime,json,os,shlex,signal,subprocess as sp,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/vllm-pd'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT.mkdir(parents=True)
REMOTE='11.163.39.110'
PYTHON=str(ROOT/'.venv-vllm/bin/python')
def ssh(cmd):return sp.check_output(['ssh','-o','BatchMode=yes',REMOTE,cmd],text=True,timeout=30)
def metric(url):
 r=requests.get(url+'/metrics',timeout=10);r.raise_for_status();return r.text
prefill='http://11.163.39.110:18910';decode='http://11.163.39.114:18920';proxy='http://127.0.0.1:18900'
manifest={'start_wall_ns':time.time_ns(),'scope':'cross-host GPU KV WRITE','model':'Qwen2.5-0.5B-Instruct','out':str(OUT)}
clock_code="import sys,time; print('READY',flush=True); [(print(time.time_ns(),flush=True)) for line in sys.stdin]"
with sp.Popen(['ssh',REMOTE,shlex.join([PYTHON,'-u','-c',clock_code])],stdin=sp.PIPE,stdout=sp.PIPE,text=True) as clock:
 assert clock.stdout.readline().strip()=='READY'
 probes=[]
 for _ in range(5):
  t0=time.time_ns();clock.stdin.write('x\n');clock.stdin.flush();tr=int(clock.stdout.readline());t1=time.time_ns()
  probes.append(dict(offset_min_ns=tr-t1,offset_max_ns=tr-t0))
 clock.stdin.close();clock.wait(timeout=10)
 manifest['clock_probes']=probes
ssh('mkdir -p '+shlex.quote(str(OUT)))
jobs=[]
for side in ['local','remote']:
 log=(OUT/(side+'-sampler.log')).open('w')
 args=[PYTHON,str(ROOT/'monitoring/sample_nics.py'),'--output',str(OUT/(side+'-nics.jsonl'))]
 if side=='remote':args=['ssh',REMOTE,f'echo $$ > {shlex.quote(str(OUT/"remote-sampler.pid"))}; exec '+shlex.join(args)]
 proc=sp.Popen(args,stdout=log,stderr=sp.STDOUT);jobs.append((side,proc,log))
 for _ in range(100):
  if 'READY' in (OUT/(side+'-sampler.log')).read_text():break
  if proc.poll() is not None:raise RuntimeError('sampler failed')
  time.sleep(.1)
 else:raise TimeoutError('sampler')
responses=[]
def request(label,prompt,url=proxy):
 payload=dict(model='qwen-kv-lab',prompt=prompt,max_tokens=32,temperature=0,seed=42,stream=False)
 start=time.time_ns();r=requests.post(url+'/v1/completions',json=payload,timeout=120);end=time.time_ns()
 r.raise_for_status();data=r.json()
 assert data['choices'][0]['text'] and data['usage']['completion_tokens']>0
 return dict(label=label,url=url,start_wall_ns=start,end_wall_ns=end,payload=payload,response=data)
try:
 for name,url in [('prefill',prefill),('decode',decode)]: (OUT/(name+'-metrics-before.txt')).write_text(metric(url))
 time.sleep(2)
 for repeat in [1,128,512]:
  prompt=('The server stores a key and a value for each attention layer. '*repeat)+'\nSummarize this in one sentence:'
  baseline=request(f'baseline-{repeat}',prompt,decode);responses.append(baseline)
  disagg=request(f'pd-{repeat}',prompt);responses.append(disagg)
  assert baseline['response']['choices'][0]['text']==disagg['response']['choices'][0]['text'],f'greedy mismatch: {repeat}'
  print('MATCH',repeat,disagg['response']['usage'],flush=True)
  time.sleep(.5)
 prompts=[('The network transfers cached attention states between GPUs. '*128)+f'\nRequest {i}: explain the benefit briefly.' for i in range(8)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  responses.extend(pool.map(lambda item:request(f'concurrent-{item[0]}',item[1]),enumerate(prompts)))
 time.sleep(2)
 for name,url in [('prefill',prefill),('decode',decode)]: (OUT/(name+'-metrics-after.txt')).write_text(metric(url))
 manifest['status']='passed'
except BaseException as exc:
 manifest['status']='failed';manifest['error']=repr(exc);raise
finally:
 (OUT/'requests.json').write_text(json.dumps(responses,indent=2))
 for side,proc,log in reversed(jobs):
  if side=='remote':ssh('kill -TERM "$(cat '+shlex.quote(str(OUT/'remote-sampler.pid'))+')"')
  else:proc.send_signal(signal.SIGTERM)
  proc.wait(timeout=20);log.close()
 sp.run(['scp',f'{REMOTE}:{OUT}/remote-nics.jsonl',str(OUT/'remote-nics.jsonl')],check=True)
 sp.run(['scp',f'{REMOTE}:{ROOT}/vllm_lab/logs/prefill.log',str(OUT/'prefill.log')],check=True)
 sp.run(['scp','-r',f'{REMOTE}:{ROOT}/vllm_lab/logs/prefill-trace',str(OUT/'prefill-trace')],check=True)
 for name in ['decode.log','proxy.log']:(OUT/name).write_bytes((ROOT/'vllm_lab/logs'/name).read_bytes())
 manifest['end_wall_ns']=time.time_ns();(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print(OUT,flush=True)
