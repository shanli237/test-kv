"""Host-wide RDMA sysfs sampling. Data counters use 4-byte units, hw counters raw."""
import argparse
import json
import os
import signal
import socket
import time
from pathlib import Path

ROOT = Path('/sys/class/infiniband')

def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None

def inventory(devices):
    result = {}
    for name in devices:
        dev = ROOT / name
        net = dev / 'device/net'
        names = [x.name for x in net.iterdir()] if net.exists() else []
        result[name] = dict(device_path=str((dev/'device').resolve()),
                           numa_node=read(dev/'device/numa_node'),
                           netdevs={n: dict(iflink=read(Path('/sys/class/net')/n/'iflink'),
                                          phys_port_name=read(Path('/sys/class/net')/n/'phys_port_name'),
                                          slaves=read(Path('/sys/class/net')/n/'bonding/slaves')) for n in names})
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--devices', default=','.join(f'mlx5_bond_{i}' for i in range(8)))
    p.add_argument('--interval', type=float, default=.1)
    p.add_argument('--duration', type=float, default=300)
    a = p.parse_args()
    if a.interval <= 0 or a.duration <= 0:
        p.error('interval and duration must be positive')
    devices = a.devices.split(',')
    missing = [n for n in devices if not (ROOT/n).exists()]
    if missing:
        p.error(f'missing devices: {missing}')
    files = []
    slow_files = []
    for name in devices:
        for port in sorted((ROOT/name/'ports').iterdir()):
            for group in ['counters', 'hw_counters']:
                for path in sorted((port/group).glob('*')):
                    if path.name == 'lifespan':  # configuration, not a cumulative counter
                        continue
                    entry = (f'{name}/{port.name}/{group}/{path.name}', path)
                    if group == 'counters' and path.name in ['port_rcv_data','port_xmit_data','port_rcv_packets','port_xmit_packets']:
                        files.append(entry)
                    else:
                        slow_files.append(entry)
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    deadline = time.monotonic()+a.duration
    next_sample = time.monotonic()
    slow_index = 0
    buckets = max(1, round(1 / a.interval))
    with open(a.output, 'w', buffering=1) as out:
        out.write(json.dumps(dict(type='metadata', host=socket.gethostname(), pid=os.getpid(),
                                  interval=a.interval, slow_interval=buckets*a.interval,
                                  inventory=inventory(devices), data_counter_unit_bytes=4,
                                  warning='Global counters; logical/physical devices may overlap.'))+'\n')
        print('READY', flush=True)
        while not stop and time.monotonic() < deadline:
            start, wall = time.monotonic_ns(), time.time_ns()
            counters, errors = {}, {}
            selected = files + slow_files[slow_index::buckets]
            slow_index = (slow_index + 1) % buckets
            for key, path in selected:
                try:
                    counters[key] = int(path.read_text())
                except (ValueError, OSError) as exc:
                    errors[key] = str(exc)
            end = time.monotonic_ns()
            out.write(json.dumps(dict(type='sample', mono_ns=start, wall_ns=wall,
                                      end_mono_ns=end, counters=counters, errors=errors))+'\n')
            next_sample += a.interval
            delay = next_sample-time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_sample = time.monotonic()
        out.write(json.dumps(dict(type='stop', mono_ns=time.monotonic_ns(), wall_ns=time.time_ns()))+'\n')

if __name__ == '__main__':
    main()
