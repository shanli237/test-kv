"""Two-process TE READ demo. Payload is synthetic KV bytes, not model output."""
import argparse
import ctypes
import json
import os
import signal
import time
from pathlib import Path
from mooncake.engine import TransferEngine

p = argparse.ArgumentParser()
p.add_argument('role', choices=['target', 'pull'])
p.add_argument('--host', default='127.0.0.1')
p.add_argument('--protocol', choices=['tcp', 'rdma'], default='tcp')
p.add_argument('--device', default='')
p.add_argument('--info', default='target.json')
a = p.parse_args()
if a.protocol == "tcp":
    os.environ["MC_FORCE_TCP"] = "1"
e = TransferEngine()
assert e.initialize(a.host + ':0', 'P2PHANDSHAKE', a.protocol, a.device) == 0
size = 1024 * 1024
buf = ctypes.create_string_buffer(size)
addr = ctypes.addressof(buf)
assert e.register_memory(addr, size) == 0
try:
    if a.role == 'target':
        ctypes.memset(addr, 0x5a, size)
        info = dict(server=f'{a.host}:{e.get_rpc_port()}', address=addr, size=size)
        Path(a.info).write_text(json.dumps(info))
        print('READY', json.dumps(info), flush=True)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            signal.pause()
        except KeyboardInterrupt:
            pass
    else:
        info = json.loads(Path(a.info).read_text())
        assert info['size'] == size
        t = time.perf_counter()
        rc = e.transfer_sync_read(info['server'], addr, info['address'], size)
        elapsed = time.perf_counter() - t
        assert rc == 0, f'READ failed: {rc}'
        assert buf.raw == b'Z' * size, 'data mismatch'
        print(f'PASS: READ {size} bytes, full payload verified, {elapsed * 1000:.3f} ms')
finally:
    e.unregister_memory(addr)
