# -*- coding: utf-8 -*-
"""最终收尾：修剪 3 条超长回复、清理残留脚本、合并导出 train.jsonl / train_shuffled.jsonl、生成批次报表。"""
import json, os, glob, random, re, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, 'batches')
SYS = open(os.path.join(ROOT, 'system_prompt.txt'), encoding='utf-8').read().strip()

CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
CN_PUNCT = re.compile(r'[\u3000-\u303f\uff00-\uffef]')
ASCII_TOKEN = re.compile(r'[A-Za-z0-9]+')


def est(text):
    n_cjk = len(CJK.findall(text))
    n_punct = len(CN_PUNCT.findall(text))
    rest = CJK.sub('', CN_PUNCT.sub('', text))
    return int(n_cjk * 0.72 + n_punct * 1.0 + sum(len(w) for w in ASCII_TOKEN.findall(rest)) / 4.0 + 0.5)


# 1) 清理残留
for junk in ('_pad.py',):
    p = os.path.join(B, junk)
    if os.path.exists(p):
        os.remove(p)
        print('removed', junk)

# 2) 修剪超 200 字回复（去掉最后一个完整句子）
files = sorted(glob.glob(os.path.join(B, '*.jsonl')))
rows = []
trimmed = 0
for f in files:
    lines = []
    for line in open(f, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        o['conversations'][0]['value'] = SYS
        for c in o['conversations']:
            if c['from'] == 'gpt' and len(c['value']) > 200:
                # 按句号/问号/叹号切最后一句去掉
                parts = re.split(r'(?<=[。！？…])', c['value'])
                while parts and len(''.join(parts)) > 200:
                    parts = parts[:-1] if len(parts) > 1 else parts
                    if len(parts) == 1 and len(''.join(parts)) > 200:
                        parts = [''.join(parts)[:195] + '……']
                c['value'] = ''.join(parts).strip() or c['value'][:195]
                trimmed += 1
        lines.append(json.dumps(o, ensure_ascii=False, separators=(',', ':')))
    open(f, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    rows.extend([json.loads(l) for l in lines])
print('trimmed', trimmed)

# 3) 校验
bad = []
for o in rows:
    convs = o['conversations']
    roles = [c['from'] for c in convs]
    if roles[0] != 'system' or convs[0]['value'] != SYS:
        bad.append((o['id'], 'system'))
    for i in range(1, len(roles)):
        if roles[i] not in ('human', 'gpt'):
            bad.append((o['id'], 'role'))
        if i >= 2 and roles[i] == roles[i - 1]:
            bad.append((o['id'], 'alternate'))
    if roles[-1] != 'gpt':
        bad.append((o['id'], 'tail'))
    if any(not c['value'].strip() for c in convs):
        bad.append((o['id'], 'empty'))
print('格式问题:', len(bad), bad[:8])

# 4) 合并导出
random.seed(42)
shuffled = rows[:]
random.shuffle(shuffled)
out1 = os.path.join(ROOT, 'train.jsonl')
out2 = os.path.join(ROOT, 'train_shuffled.jsonl')
for path, data in ((out1, rows), (out2, shuffled)):
    with open(path, 'w', encoding='utf-8') as fh:
        for o in data:
            fh.write(json.dumps(o, ensure_ascii=False, separators=(',', ':')) + '\n')

# 5) 批次报表 + 累计 token
total = 0
report = []
cum = 0
for f in files:
    objs = [json.loads(l) for l in open(f, encoding='utf-8') if l.strip()]
    t = sum(est(''.join(c['value'] for c in o['conversations'])) for o in objs)
    cum += t
    total += t
    rl = [len(c['value']) for o in objs for c in o['conversations'] if c['from'] == 'gpt']
    rounds = collections.Counter(sum(1 for c in o['conversations'] if c['from'] == 'human') for o in objs)
    report.append({
        'file': os.path.basename(f),
        'scene': objs[0]['scene'] if objs else '',
        'lines': len(objs),
        'tokens': t,
        'cum_tokens': cum,
        'avg_reply_chars': round(sum(rl) / len(rl)) if rl else 0,
        'min_reply': min(rl) if rl else 0,
        'max_reply': max(rl) if rl else 0,
        'rounds': dict(sorted(rounds.items())),
    })

with open(os.path.join(ROOT, 'REPORT.json'), 'w', encoding='utf-8') as fh:
    json.dump({'total_samples': len(rows), 'total_tokens_est': total, 'batches': report}, fh, ensure_ascii=False, indent=2)

print(f'\n样本总数: {len(rows)}   预估 token 总量: {total:,} ({total/1000:.1f}K)')
print(f"{'批次':<26}{'条数':>4}{'token':>9}{'累计':>10}{'均字':>5}{'最短':>5}{'最长':>5}")
for r in report:
    print(f"{r['file']:<26}{r['lines']:>4}{r['tokens']:>9}{r['cum_tokens']:>10}{r['avg_reply_chars']:>5}{r['min_reply']:>5}{r['max_reply']:>5}")
print('\n导出: train.jsonl, train_shuffled.jsonl, REPORT.json')
