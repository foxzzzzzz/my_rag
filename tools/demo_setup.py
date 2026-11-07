"""Local configuration checks; never invokes a model or contacts a service."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal, DecimalException
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_CONFIG=ROOT/'config/demo-models.json'
POLICY=ROOT/'config/acceptance-policy.json'

class ConfigError(Exception): pass

def read_json(path):
    try:
        with open(path,encoding='utf-8-sig') as f: return json.load(f)
    except (OSError,ValueError,UnicodeError): raise ConfigError('配置文件无法读取或 JSON 无效')

def amount(value):
    try: n=Decimal(str(value))
    except DecimalException: raise ConfigError('预算无效')
    if not n.is_finite() or n<0: raise ConfigError('预算无效')
    return n

def validate_config(c):
    try:
        if not isinstance(c,dict): raise ConfigError('配置格式无效')
        for name in ('scheme_id','region','verified_date','initial_run','source_root','ffmpeg_env'):
            if not isinstance(c[name],str) or not c[name].strip(): raise ConfigError('配置字段无效')
        providers=c['providers']; models=c['models']; d=c['doctor']; limits=c['limits']
        if not isinstance(providers,dict) or not isinstance(models,dict) or not isinstance(d,dict) or not isinstance(limits,dict): raise ConfigError('配置格式无效')
        if set(providers)!= {'dashscope','deepseek'} or set(models)!= {'asr','vision','text'}: raise ConfigError('服务商或模型配置无效')
        if not {'api_base_url','compatible_base_url','api_key_env'}.issubset(providers['dashscope']) or not {'compatible_base_url','api_key_env'}.issubset(providers['deepseek']): raise ConfigError('服务地址缺失')
        keys=[]
        for provider in providers.values():
            name=provider['api_key_env']
            if not isinstance(name,str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]*',name): raise ConfigError('密钥变量名无效')
            keys.append(name)
            urls=[v for k,v in provider.items() if k.endswith('_base_url')]
            if not urls: raise ConfigError('服务地址缺失')
            for url in urls:
                if not isinstance(url,str): raise ConfigError('服务地址无效')
                u=urlsplit(url)
                if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment: raise ConfigError('服务地址必须为 HTTPS 且不含凭据')
        if len(set(keys))!=2: raise ConfigError('密钥变量名重复')
        for name,model in models.items():
            if model['provider'] not in providers or not all(isinstance(model.get(k),str) and model[k].strip() for k in ('model','protocol')): raise ConfigError('模型配置无效')
        if models['asr'].get('upload')!='temporary_policy' or models['asr'].get('timestamp_alignment_enabled') is not True: raise ConfigError('ASR 配置无效')
        research=amount(limits['research_budget_cny']); smoke=amount(limits['smoke_budget_cny']); demo=amount(limits['initial_demo_budget_cny']); ceiling=amount(read_json(POLICY)['budget'])
        if not 0<smoke<=demo<=research<=ceiling: raise ConfigError('预算上限无效')
        for key in ('video_extensions','html_extensions','placeholder_values'):
            if not isinstance(d[key],list) or not d[key] or not all(isinstance(x,str) and x for x in d[key]): raise ConfigError('诊断配置无效')
        if not isinstance(d['ffmpeg_timeout_seconds'],(int,float)) or isinstance(d['ffmpeg_timeout_seconds'],bool) or not 0<d['ffmpeg_timeout_seconds']<=60: raise ConfigError('版本检查超时无效')
        return keys
    except (KeyError,TypeError,AttributeError,ValueError,DecimalException): raise ConfigError('配置字段或格式无效')

def dotenv(path):
    if not path.exists(): return {}
    values={}
    try:
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            match=re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)',line)
            if not match: raise ConfigError('dotenv 格式无效')
            key,val=match.groups(); val=val.strip()
            if val.startswith(('"',"'")):
                quote=val[0]; end=val.find(quote,1)
                if end<0 or (val[end+1:].strip() and not val[end+1:].strip().startswith('#')): raise ConfigError('dotenv 格式无效')
                val=val[1:end]
            else:
                val=re.split(r'\s+#',val,maxsplit=1)[0].strip()
                if any(ch in val for ch in ('"',"'")): raise ConfigError('dotenv 格式无效')
            if key in values: raise ConfigError('dotenv 变量重复')
            values[key]=val
    except (OSError,UnicodeError): raise ConfigError('dotenv 无法读取')
    return values

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def sources(c):
    rel=Path(c['source_root']); root=(ROOT/rel).resolve()
    if rel.is_absolute() or not root.is_relative_to(ROOT): raise ConfigError('素材根路径越界')
    issues=[]; files=[]; seen=set(); counts={'video':0,'html':0}
    if not root.is_dir(): return files,counts,['素材目录不存在']
    for p in root.rglob('*'):
        if p.is_symlink(): issues.append('素材目录包含符号链接'); continue
        if not p.is_file(): continue
        ext=p.suffix.lower(); d=c['doctor']
        kind='video' if ext in d['video_extensions'] else 'html' if ext in d['html_extensions'] else None
        if not kind: continue
        if not p.resolve().is_relative_to(root): issues.append('素材路径越界'); continue
        digest=sha(p); counts[kind]+=1
        if digest in seen: issues.append('素材内容重复')
        seen.add(digest); files.append({'path':p.relative_to(root).as_posix(),'kind':kind,'bytes':p.stat().st_size,'sha256':digest})
    for kind in counts:
        if not counts[kind]: issues.append('缺少视频' if kind=='video' else '缺少 HTML')
    return files,counts,issues

def ffmpeg(c, env):
    explicit=(os.environ[c['ffmpeg_env']] if c['ffmpeg_env'] in os.environ else env.get(c['ffmpeg_env'], '')).strip()
    if explicit: candidates=[explicit]
    else:
        found=shutil.which('ffmpeg'); candidates=[found] if found else []
        candidates += [str(p) for p in (ROOT/'tmp/media-inspect-deps/imageio_ffmpeg/binaries').glob('ffmpeg*') if p.is_file()]
    for path in candidates:
        try:
            result=subprocess.run([path,'-version'],capture_output=True,timeout=c['doctor']['ffmpeg_timeout_seconds'],shell=False)
            if result.returncode==0 and result.stdout.startswith(b'ffmpeg version'): return 'local-version-ok'
        except (OSError,subprocess.TimeoutExpired,ValueError): pass
    return 'unavailable'

def doctor(c, envfile):
    keys=validate_config(c); env=dotenv(envfile); placeholders={x.casefold() for x in c['doctor']['placeholder_values']}; statuses={}
    for key in keys:
        val=os.environ[key] if key in os.environ else env.get(key,'')
        statuses[key]='configured' if val.strip() and val.strip().casefold() not in placeholders else 'missing'
    files,counts,issues=sources(c); ff=ffmpeg(c,env)
    if ff=='unavailable': issues.append('FFmpeg 不可用')
    if 'missing' in statuses.values(): issues.append('密钥尚未配置')
    return {'keys':statuses,'sources':files,'counts':counts,'ffmpeg':ff,'issues':issues,'ready_for_smoke_test':not issues,'service_verified':False,'network_requests':0,'model_calls':0,'note':'仅本地检查，不验证真实服务；真实调用结果请查阅reports与验证记录'}

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    for name in ('init','doctor'):
        q=sub.add_parser(name); q.add_argument('--config',default=str(DEFAULT_CONFIG)); q.add_argument('--env-file',default=str(ROOT/'.env'))
        if name=='doctor': q.add_argument('--json',action='store_true')
    a=p.parse_args(); envfile=Path(a.env_file)
    if a.command=='init':
        template=envfile.parent/'.env.example'
        if envfile.exists():
            print('环境配置文件已存在，未覆盖')
            return 0
        try:
            with template.open('rb') as src, envfile.open('xb') as dst: shutil.copyfileobj(src,dst)
            print('已创建环境配置文件')
        except FileExistsError: print('环境配置文件已存在，未覆盖')
        return 0
    report=doctor(read_json(a.config),envfile); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report['ready_for_smoke_test'] else 1
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8'); sys.stderr.reconfigure(encoding='utf8')
    try: sys.exit(main())
    except (ConfigError,OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError,DecimalException): print('错误：配置或本地输入格式无效',file=sys.stderr); sys.exit(2)
