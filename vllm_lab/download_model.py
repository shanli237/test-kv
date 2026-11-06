"""Download the public Qwen model from its ModelScope repository; record SHA256."""
import concurrent.futures,hashlib,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent/'models/Qwen2.5-0.5B-Instruct'
root.mkdir(parents=True,exist_ok=True)
files=['config.json','generation_config.json','tokenizer.json','tokenizer_config.json','vocab.json','merges.txt','model.safetensors','LICENSE','README.md']
def download(name):
    dest=root/name
    url='https://modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct/resolve/master/'+name
    subprocess.run(['curl','-L','--fail','--retry','3','--max-time','600','-sS',url,'-o',str(dest)+'.part'],check=True)
    Path(str(dest)+'.part').rename(dest)
    h=hashlib.sha256()
    with dest.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    print('Downloaded',name,dest.stat().st_size,flush=True)
    return dict(file=name,url=url,bytes=dest.stat().st_size,sha256=h.hexdigest())
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:manifest=list(pool.map(download,files))
(root.parent.parent/'model-manifest.json').write_text(json.dumps(manifest,indent=2))
