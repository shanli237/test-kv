"""Opt-in lab tracing of Mooncake Python APIs, without modifying installed packages."""
import os
if os.getenv('VLLM_LAB_TRACE_DIR'):
    import itertools,json,threading,time
    from pathlib import Path
    import mooncake.engine as _engine
    _Original=_engine.TransferEngine
    _lock=threading.Lock()
    _ids=itertools.count()
    def _emit(event,**kw):
        row=dict(event=event,pid=os.getpid(),mono_ns=time.monotonic_ns(),wall_ns=time.time_ns(),**kw)
        with _lock:
            root=Path(os.environ['VLLM_LAB_TRACE_DIR']);root.mkdir(parents=True,exist_ok=True)
            with (root/f'te-{os.getpid()}.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    class TracedTransferEngine(_Original):
        def batch_register_memory(self,addresses,sizes,*args,**kwargs):
            rc=super().batch_register_memory(addresses,sizes,*args,**kwargs)
            _emit('register_memory',addresses=list(addresses),sizes=list(sizes),bytes=sum(sizes),rc=rc)
            return rc
        def batch_transfer_sync_write(self,remote,sources,targets,lengths,*args,**kwargs):
            transfer_id=next(_ids)
            _emit('call_start',transfer_id=transfer_id,operation='WRITE',remote=remote,bytes=sum(lengths),descriptors=len(lengths),source_first=sources[0] if sources else None,target_first=targets[0] if targets else None)
            start=time.monotonic_ns()
            try:rc=super().batch_transfer_sync_write(remote,sources,targets,lengths,*args,**kwargs)
            except BaseException as exc:
                _emit('call_end',transfer_id=transfer_id,operation='WRITE',duration_ns=time.monotonic_ns()-start,rc=None,error=type(exc).__name__)
                raise
            _emit('call_end',transfer_id=transfer_id,operation='WRITE',duration_ns=time.monotonic_ns()-start,rc=rc)
            return rc
    _engine.TransferEngine=TracedTransferEngine
