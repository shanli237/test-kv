"""Controlled CPU READ experiment; counters are host-wide, not process-specific."""
import argparse, ctypes, json, mmap, os, signal, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from monitoring.telemetry import Events

def counters():
    out = {}
    for dev in sorted(Path('/sys/class/infiniband').iterdir()):
        values = {}
        for f in (dev / 'ports/1/counters').glob('*'):
            try: values[f.name] = int(f.read_text())
            except (ValueError, OSError): pass
        out[dev.name] = values
    return out

p = argparse.ArgumentParser()
p.add_argument('role', choices=['target', 'pull', 'counters'])
p.add_argument('--host')
p.add_argument('--device', default='')
p.add_argument('--info', default='probe-target.json')
p.add_argument('--output', default='probe-result.json')
p.add_argument('--mode', choices=['single', 'batch', 'parallel'], default='single')
p.add_argument('--mib', type=int, default=256)
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--warmup', type=int, default=0)
p.add_argument('--numa', type=int)
p.add_argument('--events', help='Buffered application-level TE call events (JSONL)')
a = p.parse_args()
if a.numa is not None:
    cpus = set()
    for part in Path(f'/sys/devices/system/node/node{a.numa}/cpulist').read_text().strip().split(','):
        ends = list(map(int, part.split('-')))
        cpus.update(range(ends[0], ends[-1]+1))
    os.sched_setaffinity(0, cpus & os.sched_getaffinity(0))
events = Events(a.events)
if a.role == 'counters':
    print(json.dumps(counters())); raise SystemExit
from mooncake.engine import TransferEngine
os.environ.pop('MC_FORCE_TCP', None)
e = TransferEngine()
assert e.initialize(a.host + ':0', 'P2PHANDSHAKE', 'rdma', a.device) == 0
size = a.mib * 1024**2
mem = mmap.mmap(-1, size)
addr = ctypes.addressof(ctypes.c_char.from_buffer(mem))
ctypes.memset(addr, 0x5a if a.role == 'target' else 0, size)
assert e.register_memory(addr, size) == 0
try:
    if a.role == 'target':
        Path(a.info).write_text(json.dumps(dict(server=f'{a.host}:{e.get_rpc_port()}', address=addr, size=size)))
        print('READY', flush=True)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try: signal.pause()
        except KeyboardInterrupt: pass
    else:
        info = json.loads(Path(a.info).read_text())
        assert info['size'] == size
        before = counters()
        times = []
        chunk = 4 * 1024**2
        pool = ThreadPoolExecutor(max_workers=4) if a.mode == "parallel" else None
        for i in range(-a.warmup, a.repeats):
            ctypes.memset(addr, 0, size)
            print(f'BEGIN iteration={i} mode={a.mode}', flush=True)
            start = time.perf_counter()
            if a.mode == 'single':
                rc = events.call(e.transfer_sync_read, info['server'], addr, info['address'], size, bytes_count=size, iteration=i, mode=a.mode)
            elif a.mode == 'parallel':
                part = size // 4
                futures = [pool.submit(events.call, e.transfer_sync_read, info['server'], addr+x*part, info['address']+x*part, part, bytes_count=part, iteration=i, mode=a.mode) for x in range(4)]
                rc = max(abs(f.result()) for f in futures)
            else:
                offsets = list(range(0, size, chunk))
                rc = events.call(e.batch_transfer_sync_read, info['server'], [addr+x for x in offsets], [info['address']+x for x in offsets], [min(chunk, size-x) for x in offsets], bytes_count=size, iteration=i, mode=a.mode, requests=len(offsets))
            elapsed = time.perf_counter()-start
            assert rc == 0, rc
            # Verify in bounded chunks, outside the timed transfer.
            for off in range(0, size, chunk):
                assert mem[off:off+chunk] == b'Z'*min(chunk, size-off), off
            events.emit('verified', iteration=i, mode=a.mode, bytes=size)
            if i >= 0: times.append(elapsed)
            print(f'PASS iteration={i} bytes={size} seconds={elapsed:.6f}', flush=True)
        if pool: pool.shutdown()
        Path(a.output).write_text(json.dumps(dict(mode=a.mode, warmup=a.warmup, numa=a.numa, bytes_per_iteration=size, repeats=a.repeats, seconds=times, verified=True, before=before, after=counters()), indent=2))
finally:
    events.close()
    e.unregister_memory(addr)
    mem.close()
