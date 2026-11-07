import argparse, hashlib, zipfile, os, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'personalkb':{'.py'},'config':{'.json','.txt','.sources','.conf'},'tools':{'.py'},'deploy':{'.py','.yaml','.template','.sh','.md'},'web':{'.json','.js','.jsx','.ts','.tsx','.css','.html','.svg'}}
def build(output, force=False):
    output=Path(output); checksum=output.with_suffix(output.suffix+'.sha256')
    if not force and (output.exists() or checksum.exists()): raise FileExistsError('output exists; use --force')
    entries={}
    for directory,exts in ALLOWED.items():
        for p in sorted((ROOT/directory).rglob('*')):
            rel=p.relative_to(ROOT)
            if p.is_file() and not any((ROOT.joinpath(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)) and p.suffix in exts and not any(x in rel.parts for x in ('node_modules','dist','__pycache__')): entries[rel.as_posix()]=p.read_bytes()
    for name in ('.dockerignore','deploy/Dockerfile','README.md','docs/phase-4-server-guide.md','docs/phase-4-validation.md','docs/phase-4-deployment-contract.md','docs/phase-4-test-cases.md'): entries[name]=(ROOT/name).read_bytes()
    sums=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(entries.items()))
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=output.parent,prefix='.kit-',suffix='.zip'); os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in sorted(entries.items()):
                info=zipfile.ZipInfo(name); info.create_system=3
                info.external_attr=((0o100755 if name.endswith('.sh') else 0o100644) << 16)
                info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,data)
            info=zipfile.ZipInfo('SHA256SUMS'); info.create_system=3
            info.external_attr=0o100644 << 16; info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,sums)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None: raise ValueError('ZIP CRC failure')
            for name,data in entries.items():
                if hashlib.sha256(z.read(name)).digest()!=hashlib.sha256(data).digest(): raise ValueError('ZIP hash failure')
        digest=hashlib.sha256(Path(tmp).read_bytes()).hexdigest()
        os.replace(tmp,output)
        checksum.write_text(digest+'  '+output.name+'\n',encoding='ascii')
    finally:
        if Path(tmp).exists(): Path(tmp).unlink()
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True); p.add_argument('--force',action='store_true'); a=p.parse_args(); build(a.output,a.force)
