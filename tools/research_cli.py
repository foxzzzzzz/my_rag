import argparse, hashlib, json, sys, math
from pathlib import Path
from decimal import Decimal, InvalidOperation, DecimalException
ROOT = Path(__file__).resolve().parent.parent

def load(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f)

def digest(path: Path) -> str:
    """Stream a file into SHA-256 without loading media into memory."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def money(value: object) -> Decimal:
    try:
        n = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('金额未知或无效')
    if not n.is_finite() or n < 0:
        raise ValueError('金额必须是非负有限数')
    return n

def ratio_pass(a: int, b: int, t: Decimal) -> bool:
    return b > 0 and Decimal(a) >= Decimal(b) * t

def config(path: str) -> dict:
    """Load and check the external quality and budget thresholds."""
    c = load(path)
    for k in ('video_count', 'dev_count', 'acceptance_count', 'html_count', 'fact_count'):
        if type(c[k]) is not int or c[k] <= 0:
            raise ValueError('配置数量无效: ' + k)
    if c['video_count'] != c['dev_count'] + c['acceptance_count']:
        raise ValueError('视频数量不一致')
    for k in ('accuracy', 'coverage'):
        if not 0 < money(c[k]) <= 1:
            raise ValueError('配置阈值无效: ' + k)
    if money(c['budget']) <= 0:
        raise ValueError('预算无效')
    extensions = c['extensions']
    if not isinstance(extensions, dict) or set(extensions) != {'video', 'html'} or any(not isinstance(v, list) or not v or not all(isinstance(x, str) and x.startswith('.') for x in v) for v in extensions.values()):
        raise ValueError('配置扩展名无效')
    if not isinstance(c['required_tags'], list) or not all(isinstance(x, str) and x for x in c['required_tags']):
        raise ValueError('配置类别无效')
    return c

def validate(manifest: str, root: str, c: dict) -> tuple[dict, dict]:
    """Validate sample metadata, content hashes, annotations, and coverage."""
    m = load(manifest)
    root = Path(root).resolve()
    seen = set()
    files = {}
    facts = 0
    tags = set()
    counts = {'dev': 0, 'acceptance': 0, 'html': 0}
    hashes = {}
    if set(m) != {'samples'} or not isinstance(m['samples'], list):
        raise ValueError('清单字段无效')
    for s in m['samples']:
        if set(s) != {'id', 'kind', 'split', 'path', 'sha256', 'annotation', 'duration_seconds', 'tags', 'rights_confirmed'} or not isinstance(s['id'], str) or (not s['id']) or (s['id'] in seen):
            raise ValueError('样本字段或 ID 无效')
        seen.add(s['id'])
        kind = s['kind']
        split = s['split']
        if s['rights_confirmed'] is not True or not isinstance(s['tags'], list) or (not all((isinstance(t, str) and t for t in s['tags']))):
            raise ValueError('授权或标签无效')
        tags.update(s['tags'])
        duration = s['duration_seconds']
        if kind == 'video' and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or (not math.isfinite(duration)) or (duration <= 0)):
            raise ValueError('视频时长无效')
        if kind == 'html' and duration is not None:
            raise ValueError('HTML 时长必须为空')
        if Path(s['path']).suffix.lower() not in c['extensions'].get(kind, []):
            raise ValueError('文件扩展名无效')
        if kind == 'video' and split in ('dev', 'acceptance'):
            counts[split] += 1
        elif kind == 'html' and split == 'html':
            counts['html'] += 1
        else:
            raise ValueError('样本类型或分集无效: ' + s['id'])
        for key in ('path', 'annotation'):
            rel = s[key]
            if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
                raise ValueError('路径无效')
            p = (root / rel).resolve()
            if not p.is_relative_to(root) or not p.is_file():
                raise ValueError('路径越界或文件不存在: ' + rel)
            h = digest(p)
            hashes[rel] = h
            if key == 'path':
                if h != s['sha256']:
                    raise ValueError('哈希不符: ' + s['id'])
                if h in files:
                    raise ValueError('媒体文件重复: ' + s['id'])
                files[h] = split
        a = load(root / s['annotation'])
        if set(a) != {'reviewer', 'confirmed', 'facts'} or not isinstance(a['reviewer'], str) or (not a['reviewer'].strip()) or (a['confirmed'] is not True) or (not isinstance(a['facts'], list)):
            raise ValueError('标注未经确认: ' + s['id'])
        ids = set()
        for f in a['facts']:
            if set(f) != {'id', 'text', 'evidence'} or not all((isinstance(f[k], str) and f[k].strip() for k in ('id', 'text'))) or f['id'] in ids:
                raise ValueError('事实无效: ' + s['id'])
            if kind == 'video' and (not valid_evidence(f['evidence'], duration)):
                raise ValueError('事实证据无效: ' + s['id'])
            ids.add(f['id'])
        if kind == 'video':
            if not ids:
                raise ValueError('视频标注为空: ' + s['id'])
            facts += len(ids)
    for k, ck in [('dev', 'dev_count'), ('acceptance', 'acceptance_count'), ('html', 'html_count')]:
        if counts[k] < c[ck]:
            raise ValueError('数量不足: ' + k)
    if facts < c['fact_count']:
        raise ValueError('事实数量不足')
    if not set(c['required_tags']).issubset(tags):
        raise ValueError('必备类别缺失')
    return (m, hashes)

def valid_evidence(e: object, duration: float) -> bool:
    """Check evidence structure and clip bounds; semantic review remains human."""
    if not isinstance(e, dict) or set(e) != {'type', 'start', 'end'} or e['type'] not in ('audio', 'visual', 'audio_visual'):
        return False
    start, end = (e['start'], e['end'])
    return all((isinstance(x, (int, float)) and (not isinstance(x, bool)) and math.isfinite(x) for x in (start, end))) and 0 <= start < end <= duration

def evaluate(a: argparse.Namespace, c: dict, m: dict, lock: dict, policy: dict) -> int:
    """Verify the frozen inputs and score all videos in the chosen split."""
    if load(a.lock) != lock:
        raise ValueError('锁文件与当前样本不匹配')
    r = load(a.results)
    if set(r) != {'split', 'version', 'reviewer', 'confirmed', 'samples'} or r['split'] not in ('dev', 'acceptance') or r['version'] not in ('machine_initial', 'human_reviewed') or (not isinstance(r['reviewer'], str)) or (not r['reviewer'].strip()) or (r['confirmed'] is not True):
        raise ValueError('结果元数据无效')
    expected = {s['id']: s for s in m['samples'] if s['kind'] == 'video' and s['split'] == r['split']}
    results = r['samples']
    if not isinstance(results, list) or len(results) != len(expected) or {x['id'] for x in results} != set(expected):
        raise ValueError('结果样本不完整或重复')
    correct = denom = goldtotal = 0
    matched = set()
    for result in results:
        if set(result) != {'id', 'predictions'} or not isinstance(result['predictions'], list):
            raise ValueError('预测格式无效')
        gold = {x['id'] for x in load(Path(a.root) / expected[result['id']]['annotation'])['facts']}
        goldtotal += len(gold)
        preds = {}
        for x in result['predictions']:
            if set(x) != {'id', 'text', 'decision', 'gold_id', 'evidence', 'duplicate_of'} or not isinstance(x['id'], str) or (not x['id']) or (x['id'] in preds) or (not isinstance(x['text'], str)) or (not x['text'].strip()) or (x['decision'] not in ('correct', 'incorrect', 'duplicate')):
                raise ValueError('预测无效')
            preds[x['id']] = x
        for x in preds.values():
            if x['decision'] == 'duplicate':
                if x['duplicate_of'] not in preds or preds[x['duplicate_of']]['decision'] == 'duplicate':
                    raise ValueError('重复引用无效')
                continue
            denom += 1
            if x['decision'] == 'correct':
                e = x['evidence']
                if x['gold_id'] not in gold or not valid_evidence(e, expected[result['id']]['duration_seconds']) or (result['id'], x['gold_id']) in matched:
                    raise ValueError('正确项证据或映射无效')
                matched.add((result['id'], x['gold_id']))
                correct += 1
    passed = ratio_pass(correct, denom, money(c['accuracy'])) and ratio_pass(len(matched), goldtotal, money(c['coverage']))
    counts = {split: sum(s['kind'] == 'video' and s['split'] == split for s in m['samples']) for split in ('dev', 'acceptance')}
    html_count = sum(s['kind'] == 'html' for s in m['samples'])
    fact_count = sum(len(load(Path(a.root) / s['annotation'])['facts']) for s in m['samples'] if s['kind'] == 'video')
    baseline = (counts['dev'] >= policy['dev_count'] and counts['acceptance'] >= policy['acceptance_count']
                and sum(counts.values()) >= policy['video_count'] and html_count >= policy['html_count']
                and fact_count >= policy['fact_count']
                and money(c['accuracy']) >= money(policy['accuracy'])
                and money(c['coverage']) >= money(policy['coverage']))
    eligible = baseline and r['split'] == 'acceptance' and r['version'] == 'machine_initial'
    reasons = []
    if not baseline: reasons.append('样本数量或配置阈值未满足正式基线')
    if r['split'] != 'acceptance': reasons.append('非验收集')
    if r['version'] != 'machine_initial': reasons.append('非机器初始版本')
    if not passed: reasons.append('准确率或覆盖率未达配置阈值')
    print(json.dumps({'evaluation_mode': 'annotated_benchmark', 'current_workflow_gate': False, 'correct': correct, 'predictions': denom, 'matched_gold': len(matched), 'gold': goldtotal, 'accuracy': str(Decimal(correct)/Decimal(denom)) if denom else None, 'coverage': str(Decimal(len(matched))/Decimal(goldtotal)) if goldtotal else None, 'accuracy_threshold': str(c['accuracy']), 'coverage_threshold': str(c['coverage']), 'reasons': reasons, 'passed': passed, 'formal_eligible': eligible, 'formal_pass': passed and eligible, 'note': '仅检查人工标注结构，不能证明语义正确；机器原输出经人工评分，人工修订需单独报告。'}, ensure_ascii=False))
    return 1 if eligible and (not passed) else 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--config', default=str(ROOT / 'config/research.json'))
    sub = p.add_subparsers(dest='cmd', required=True)
    for cmd in ('validate', 'freeze', 'evaluate'):
        q = sub.add_parser(cmd)
        q.add_argument('--manifest', required=True)
        q.add_argument('--root', required=True)
        if cmd in ('freeze', 'evaluate'):
            q.add_argument('--lock', required=True)
        if cmd == 'evaluate':
            q.add_argument('--results', required=True)
    q = sub.add_parser('budget-check')
    q.add_argument('--actual', required=True)
    q.add_argument('--pending', required=True)
    q.add_argument('--new', required=True)
    a = p.parse_args()
    c = config(a.config)
    policy = config(ROOT / 'config/acceptance-policy.json')
    if a.cmd == 'budget-check':
        total = sum(map(money, [a.actual, a.pending, a.new]))
        ok = total <= min(money(c['budget']), money(policy['budget']))
        print(json.dumps({'total': str(total), 'allowed': ok, 'note': '离线上界预检，不能阻断外部调用'}, ensure_ascii=False))
        return 0 if ok else 1
    m, h = validate(a.manifest, a.root, c)
    lock = {'manifest': m, 'files': h, 'config': c, 'policy': policy}
    if a.cmd == 'freeze':
        with open(a.lock, 'x', encoding='utf-8') as f:
            json.dump(lock, f, ensure_ascii=False, sort_keys=True, indent=2)
    if a.cmd == 'evaluate':
        return evaluate(a, c, m, lock, policy)
    print(json.dumps({'status': 'ok', 'note': '离线结构检查，未证明模型质量'}, ensure_ascii=False))
    return 0
if __name__ == '__main__':
    # Make JSON and diagnostics stable across Windows console code pages.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, OverflowError, AttributeError, IndexError, RecursionError, DecimalException) as e:
        print('错误: ' + str(e), file=sys.stderr)
        sys.exit(2)
