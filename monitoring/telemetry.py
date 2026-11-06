"""Optional buffered application events; not NIC hardware queue telemetry."""
import json
import threading
import time
from pathlib import Path

class Events:
    def __init__(self, path):
        self.path = path
        self.rows = []
        self.lock = threading.Lock()
        self.sequence = 0

    def emit(self, kind, **fields):
        if not self.path:
            return
        with self.lock:
            self.rows.append(dict(event=kind, mono_ns=time.monotonic_ns(),
                                  wall_ns=time.time_ns(), **fields))

    def call(self, function, *args, bytes_count, iteration, mode, requests=1):
        if not self.path:
            return function(*args)
        with self.lock:
            transfer_id = self.sequence
            self.sequence += 1
        self.emit('call_start', transfer_id=transfer_id, bytes=bytes_count,
                  iteration=iteration, mode=mode, requests=requests)
        start = time.monotonic_ns()
        try:
            rc = function(*args)
        except BaseException as exc:
            end = time.monotonic_ns()
            self.emit('call_end', mode=mode, transfer_id=transfer_id, duration_ns=end-start,
                      rc=None, error=type(exc).__name__)
            raise
        self.emit('call_end', mode=mode, transfer_id=transfer_id,
                  duration_ns=time.monotonic_ns()-start, rc=rc)
        return rc

    def close(self):
        if self.path:
            Path(self.path).write_text(''.join(json.dumps(x)+'\n' for x in self.rows))
