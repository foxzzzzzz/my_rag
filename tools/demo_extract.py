from html.parser import HTMLParser
from html import unescape
from pathlib import Path
import re
import subprocess

class Parser(HTMLParser):
    def __init__(self, use_main, assets):
        super().__init__(convert_charrefs=False)
        self.use_main=use_main; self.assets=assets; self.active=0; self.skip=0; self.title_on=False; self.title=''; self.out=[]; self.svg=[]; self.svg_depth=0; self.svg_files=[]; self.table=[]; self.row=None; self.cell=None; self.pre=0; self.stats={'table':0,'code':0,'svg':0,'textchars':0}
    def handle_starttag(self, tag, attrs):
        raw=self.get_starttag_text()
        if self.svg_depth:
            self.svg.append(raw); self.svg_depth+=1; return
        if tag=='title': self.title_on=True
        if tag in ('main' if self.use_main else 'body',): self.active+=1
        if not self.active: return
        if tag in ('script','style','nav','head'): self.skip+=1; return
        if self.skip: return
        if tag=='svg': self.svg=[raw]; self.svg_depth=1; return
        if re.fullmatch(r'h[1-6]',tag): self.out.append('\n\n'+'#'*int(tag[1])+' ')
        elif tag=='li': self.out.append('\n- ')
        elif tag in ('p','div','section','article','br'): self.out.append('\n')
        elif tag=='pre': self.pre+=1; self.stats['code']+=1; self.out.append('\n```\n')
        elif tag=='table': self.table=[]; self.stats['table']+=1
        elif tag=='tr': self.row=[]
        elif tag in ('td','th'): self.cell=[]
    def handle_startendtag(self,tag,attrs):
        if self.svg_depth: self.svg.append(self.get_starttag_text())
        else: self.handle_starttag(tag,attrs); self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if self.svg_depth:
            self.svg.append('</'+tag+'>'); self.svg_depth-=1
            if not self.svg_depth:
                self.assets.mkdir(parents=True,exist_ok=True); p=self.assets/('svg-%03d.svg'%(len(self.svg_files)+1)); p.write_text(''.join(self.svg),encoding='utf-8'); self.svg_files.append(str(p)); self.out.append('\n[SVG: '+p.name+']\n'); self.stats['svg']+=1
            return
        if tag=='title': self.title_on=False
        if tag in ('main' if self.use_main else 'body',): self.active-=1; return
        if not self.active: return
        if tag in ('script','style','nav','head') and self.skip: self.skip-=1; return
        if self.skip: return
        if tag=='pre': self.pre-=1; self.out.append('\n```\n')
        elif tag in ('td','th') and self.cell is not None: self.row.append(''.join(self.cell).strip().replace('|','\\|')); self.cell=None
        elif tag=='tr' and self.row is not None: self.table.append(self.row); self.row=None
        elif tag=='table' and self.table:
            self.out.append('\n'+'\n'.join('| '+' | '.join(row)+' |' for row in [self.table[0], ['---']*len(self.table[0]), *self.table[1:]])+'\n')
        elif tag in ('p','li') or re.fullmatch(r'h[1-6]',tag): self.out.append('\n')
    def handle_entityref(self, name):
        value = '&' + name + ';'
        self.handle_data(value if self.svg_depth else unescape(value))
    def handle_charref(self, name):
        value = '&#' + name + ';'
        self.handle_data(value if self.svg_depth else unescape(value))
    def handle_data(self,data):
        if self.svg_depth: self.svg.append(data); return
        if self.title_on: self.title+=data
        if self.active and not self.skip:
            self.stats['textchars']+=len(data)
            if self.cell is not None: self.cell.append(data)
            elif self.row is None: self.out.append(data if self.pre else re.sub(r'\s+',' ',data))

def extract_html(path, assets_dir):
    content=Path(path).read_text(encoding='utf-8-sig',errors='replace')
    parser=Parser(bool(re.search(r'<main(?:\s|>)',content,re.I)),Path(assets_dir)); parser.feed(content)
    raw_svgs=re.findall(r'<svg\b[^>]*>[\s\S]*?</svg\s*>',content,re.I)
    if len(raw_svgs)==len(parser.svg_files):
        for filename, raw in zip(parser.svg_files,raw_svgs):
            Path(filename).write_text(raw,encoding='utf-8',newline='')
    return {'title':parser.title.strip(),'markdown':''.join(parser.out).strip(),'svg_context':'\n'.join(Path(p).read_text(encoding='utf-8') for p in parser.svg_files),'svg_files':parser.svg_files,'stats':parser.stats}

def probe_media(path, ffmpeg, timeout):
    result=subprocess.run([str(ffmpeg),'-hide_banner','-i',str(path)],capture_output=True,text=True,errors='replace',timeout=timeout,shell=False)
    s=result.stderr; duration=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',s); video=re.search(r'Video:.*?\b(\d{2,})x(\d{2,})\b',s)
    return {'duration_seconds':int(duration[1])*3600+int(duration[2])*60+float(duration[3]) if duration else None,'width':int(video[1]) if video else None,'height':int(video[2]) if video else None,'has_audio':bool(re.search(r'Stream.*Audio:',s))}

def extract_audio(path,target,ffmpeg,config):
    subprocess.run([str(ffmpeg),'-hide_banner','-y','-i',str(path),'-vn','-ac',str(config['audio_channels']),'-ar',str(config['audio_sample_rate']),'-c:a','pcm_s16le',str(target)],check=True,capture_output=True,timeout=config['timeout'],shell=False)
