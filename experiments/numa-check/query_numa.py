import ctypes, json, mmap, os
m=mmap.mmap(-1,4096);m[0]=1
addr=ctypes.addressof(ctypes.c_char.from_buffer(m))
lib=ctypes.CDLL('libnuma.so.1',use_errno=True)
lib.numa_move_pages.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int),ctypes.c_int]
pages=(ctypes.c_void_p*1)(addr);status=(ctypes.c_int*1)(-999)
r=lib.numa_move_pages(0,1,pages,None,status,0)
print(json.dumps(dict(host=os.uname().nodename,rc=r,errno=ctypes.get_errno(),page_node=status[0])))
