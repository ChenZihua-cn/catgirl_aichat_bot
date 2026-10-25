# -*- coding: utf-8 -*-
"""规范化：把所有样本的 system 字段替换为 system_prompt.txt 的逐字原文，并按 file 重写为紧凑单行 JSON。
可选：--fix-len 会报告超出 50-200 字区间的 gpt 回复（不自动改写，避免破坏语义）。"""
import json, os, glob, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYS = open(os.path.join(ROOT, 'system_prompt.txt'), encoding='utf-8').read().strip()

targets = sys.argv[1:] or [os.path.join(ROOT, 'batches', '*.jsonl')]
files = []
for p in targets:
    files.extend(sorted(glob.glob(p)))
files = [f for f in files if os.path.isfile(f) and f.endswith('.jsonl')]

changed = 0
total = 0
over = []
under = []
dup = collections.Counter()
dup_open = collections.Counter()

for f in files:
    out = []
    for line in open(f, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        total += 1
        convs = o['conversations']
        if convs[0]['from'] != 'system':
            convs.insert(0, {'from': 'system', 'value': SYS})
            changed += 1
        elif convs[0]['value'] != SYS:
            convs[0]['value'] = SYS
            changed += 1
        for c in convs:
            if c['from'] == 'gpt':
                L = len(c['value'])
                if L > 200:
                    over.append((o['id'], L))
                if L < 50:
                    under.append((o['id'], L))
                dup[c['value']] += 1
            if c['from'] == 'human':
                dup_open[c['value'][:12]] += 1
        out.append(json.dumps(o, ensure_ascii=False, separators=(',', ':')))
    with open(f, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')

print(f'处理文件 {len(files)} 个，样本 {total} 条，system 修正 {changed} 条')
print(f'gpt 回复超 200 字: {len(over)} 条  示例: {over[:5]}')
print(f'gpt 回复不足 50 字: {len(under)} 条  示例: {under[:5]}')
rep = [(v, c) for v, c in dup.items() if c > 1]
print(f'完全重复的 gpt 回复: {len(rep)} 组')
for v, c in rep[:5]:
    print('   x%d %s' % (c, v[:60]))
rep2 = [(v, c) for v, c in dup_open.items() if c > 3]
print(f'重复 human 开场(前12字)超过 3 次的: {len(rep2)} 组')
for v, c in rep2[:8]:
    print('   x%d %s' % (c, v))
