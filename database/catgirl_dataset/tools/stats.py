# -*- coding: utf-8 -*-
"""评估 JSONL 训练集的 token 数与基本质量。优先使用真实 Qwen tokenizer，失败则回退到启发式估算。"""
import json, os, re, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
CN_PUNCT = re.compile(r'[\u3000-\u303f\uff00-\uffef]')
ASCII_TOKEN = re.compile(r'[A-Za-z0-9]+')

USE = os.environ.get('EST_TOKENIZER', 'auto').lower()  # auto | real | heuristic
_tok = None
_tok_err = None
if USE != 'heuristic':
    try:
        os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '8')
        from transformers import AutoTokenizer
        for name in ("Qwen/Qwen2.5-4B", "Qwen/Qwen2.5-0.5B"):
            try:
                _tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
                break
            except Exception as e:  # noqa
                _tok_err = str(e)[:120]
    except Exception as e:  # noqa
        _tok_err = str(e)[:120]


def heuristic(text: str) -> int:
    """中文约 0.72 token/字，中文标点约 1 token/个，英文/数字约 4 字符 1 token。"""
    n_cjk = len(CJK.findall(text))
    n_punct = len(CN_PUNCT.findall(text))
    rest = CJK.sub('', CN_PUNCT.sub('', text))
    n_ascii = sum(len(w) for w in ASCII_TOKEN.findall(rest))
    return int(n_cjk * 0.72 + n_punct * 1.0 + n_ascii / 4.0 + 0.5)


def count_tokens(text: str) -> int:
    if _tok is not None:
        return len(_tok.encode(text, add_special_tokens=False))
    return heuristic(text)


def iter_jsonl(paths):
    for p in paths:
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    yield p, json.loads(line)


def main(paths):
    mode = "真实 Qwen tokenizer" if _tok is not None else f"启发式估算 (transformers 不可用: {_tok_err})"
    files = []
    for p in paths:
        files.extend(sorted(glob.glob(p)) if any(c in p for c in '*?[') else [p])
    files = sorted(set(f for f in files if os.path.isfile(f)))

    total_hist = None
    if _tok is not None:
        try:
            from transformers import AutoTokenizer as _AT
            total_hist = None
        except Exception:
            pass

    n = 0
    total_tok = 0
    scene_stat = {}
    turn_stat = {}
    len_stat = []
    problems = []
    lensumaculture = 0

    # 用作损失估算：每条样本全部 assistant 文本
    for p, obj in iter_jsonl(files):
        n += 1
        convs = obj.get('conversations', [])
        text_all = ''.join(c.get('value', '') for c in convs)
        t = count_tokens(text_all)
        total_tok += t
        scene = obj.get('scene', '未标注')
        scene_stat[scene] = scene_stat.get(scene, 0) + 1
        rounds = sum(1 for c in convs if c.get('from') == 'human')
        turn_stat[rounds] = turn_stat.get(rounds, 0) + 1
        for c in convs:
            if c.get('from') == 'gpt':
                L = len(c.get('value', ''))
                len_stat.append(L)
                lensumaculture += L
        # 校验
        roles = [c.get('from') for c in convs]
        if not convs or roles[0] != 'system':
            problems.append(f'{os.path.basename(p)}#{n}: 首条不是 system')
        for i in range(1, len(roles)):
            if roles[i] not in ('human', 'gpt'):
                problems.append(f'{os.path.basename(p)}#{n}: 非法 role {roles[i]}')
            if i >= 2 and roles[i] == roles[i - 1] and roles[i] in ('human', 'gpt'):
                problems.append(f'{os.path.basename(p)}#{n}: 角色连续重复 {roles[i]}')
        if roles and roles[-1] != 'gpt':
            problems.append(f'{os.path.basename(p)}#{n}: 末轮不是 gpt')
        if any(not c.get('value', '').strip() for c in convs):
            problems.append(f'{os.path.basename(p)}#{n}: 存在空 value')

    print(f'统计模式: {mode}')
    print(f'文件数: {len(files)}')
    print(f'样本总数: {n}')
    print(f'预估 token 总数: {total_tok:,}  (约 {total_tok/1000:.1f}K)')
    if len_stat:
        print(f'assistant 回复条数: {len(len_stat)}  平均字数: {sum(len_stat)/len(len_stat):.0f}  最短: {min(len_stat)}  最长: {max(len_stat)}')
    print('轮次分布:', dict(sorted(turn_stat.items())))
    print('场景分布:')
    for k, v in sorted(scene_stat.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v}')
    if problems:
        print(f'!! 发现 {len(problems)} 处格式问题:')
        for x in problems[:20]:
            print('   ', x)
    else:
        print('格式校验: 全部通过')


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        args = [os.path.join(ROOT, '*.jsonl'), os.path.join(ROOT, 'batches', '*.jsonl')]
    main(args)
