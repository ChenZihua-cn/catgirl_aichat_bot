# -*- coding: utf-8 -*-
"""校验猫娘傲娇女友微调数据集：格式、人设一致性、长度、去重、token 统计。

用法:
    python validate.py            # 校验 data/batch_*.jsonl 并输出统计
    python validate.py merge      # 额外合并为 train.jsonl
"""
import json
import os
import re
import sys
import glob
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SAMPLE_FILE = os.path.join(ROOT, "samples", "samples_5.jsonl")
SYSTEM_FILE = os.path.join(ROOT, "system_prompt.txt")

SCENES = [
    "morning_wakeup", "cooking_meal", "housework", "commute",
    "work_school", "overtime", "shopping", "movie_tv",
    "illness_care", "quarrel_reconcile", "bedtime", "weekend_outing",
    "gaming_hobby", "anniversary_gift", "study_exam", "weather_rain",
]

BANNED = [
    "AI", "人工智能", "模型", "语言模型", "训练", "数据集", "微调", "OpenAI",
    "Qwen", "千问", "通义", "我不能", "作为一个", "扮演", "角色扮演",
    "系统提示", "指令", "脚本", "设定如下", "人设如下", "作为一只猫娘",
]

CAT_WORDS = ["喵", "本喵", "咱"]


def load_system():
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        return f.read().strip()


def iter_files():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.jsonl")))
    return files


def count_tokens(texts):
    """优先用本地 Qwen tokenizer.json（真实分词），失败则按字符数估算。"""
    local = os.path.join(ROOT, "tools", "qwen_tokenizer.json")
    try:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(local)
        n = sum(len(tok.encode(t, add_special_tokens=False).ids) for t in texts)
        return n, "qwen-tokenizer(tokenizer.json, 真实分词)"
    except Exception as e:  # noqa
        chars = sum(len(t) for t in texts)
        return int(chars * 0.78), "estimate(chars*0.78): %s" % str(e)[:80]


def main():
    do_merge = "merge" in sys.argv
    system = load_system()
    files = iter_files() + ([SAMPLE_FILE] if os.path.exists(SAMPLE_FILE) else [])

    errors = defaultdict(list)
    scene_counter = Counter()
    turn_counter = Counter()
    gpt_lens = []
    cat_hit = 0
    gpt_total = 0
    all_samples = []
    jsonl_texts = []
    seen_first = Counter()
    seen_gpt = Counter()
    dup_lines = []

    for fp in files:
        base = os.path.basename(fp)
        with open(fp, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                jsonl_texts.append(line)
                tag = "%s:%d" % (base, ln)
                try:
                    obj = json.loads(line)
                except Exception as e:
                    errors["json_parse"].append("%s %s" % (tag, e))
                    continue
                if set(obj.keys()) != {"scene", "conversations"}:
                    errors["keys"].append("%s keys=%s" % (tag, list(obj.keys())))
                scene = obj.get("scene")
                if scene not in SCENES:
                    errors["scene"].append("%s %s" % (tag, scene))
                scene_counter[scene] += 1
                conv = obj.get("conversations", [])
                if not conv or conv[0].get("from") != "system":
                    errors["no_system"].append(tag)
                else:
                    if conv[0].get("value", "").strip() != system:
                        errors["system_mismatch"].append(tag)
                if sum(1 for c in conv if c.get("from") == "system") != 1:
                    errors["multi_system"].append(tag)
                roles = [c.get("from") for c in conv[1:]]
                if roles and roles[0] != "human":
                    errors["start_role"].append(tag)
                if roles and roles[-1] != "gpt":
                    errors["end_role"].append(tag)
                for i in range(1, len(roles)):
                    if roles[i] == roles[i - 1]:
                        errors["alternate"].append(tag)
                        break
                if any(set(c.keys()) != {"from", "value"} for c in conv):
                    errors["msg_keys"].append(tag)
                turns = roles.count("gpt")
                turn_counter[turns] += 1
                if not (2 <= turns <= 6):
                    errors["turns"].append("%s %d" % (tag, turns))
                for c in conv[1:]:
                    v = c.get("value", "")
                    if c["from"] == "gpt":
                        n = len(v)
                        gpt_lens.append(n)
                        gpt_total += 1
                        if not (50 <= n <= 200):
                            errors["gpt_len"].append("%s len=%d" % (tag, n))
                        if any(w in v for w in CAT_WORDS):
                            cat_hit += 1
                        key = v[:10]
                        seen_first[key] += 1
                        if v in seen_gpt:
                            dup_lines.append("%s duplicate-of %s" % (tag, seen_gpt[v]))
                        seen_gpt[v] = tag
                    for w in BANNED:
                        if w in v:
                            errors["banned:%s" % w].append("%s | %s" % (tag, v[:40]))
                all_samples.append(obj)

    # 统计
    chars = sum(len(t) for t in jsonl_texts)
    tokens, tok_mode = count_tokens(jsonl_texts)
    # 纯文本（不含 JSON 语法与 scene 字段）的 token 数，供参考
    content_texts = ["\n".join(c["value"] for c in obj["conversations"]) for obj in all_samples]
    content_tokens, _ = count_tokens(content_texts)
    dup_open = [(k, v) for k, v in seen_first.items() if v > 1]

    print("=" * 60)
    print("文件数: %d" % len(files))
    print("样本总数: %d" % len(all_samples))
    print("对话总轮数分布: %s" % dict(sorted(turn_counter.items())))
    print("gpt 回复数: %d  平均字数: %.1f  (min %d / max %d)" % (
        gpt_total, sum(gpt_lens) / max(len(gpt_lens), 1), min(gpt_lens or [0]), max(gpt_lens or [0])))
    print("含猫娘口吻词的回复占比: %.1f%% (%d/%d)" % (
        100.0 * cat_hit / max(gpt_total, 1), cat_hit, gpt_total))
    print("字符数: %d" % chars)
    print("Token 数-整文件(%s): %d" % (tok_mode, tokens))
    print("Token 数-纯对话文本: %d" % content_tokens)
    print("-" * 60)
    print("场景分布 (%d 类):" % len(scene_counter))
    for s, n in sorted(scene_counter.items(), key=lambda x: -x[1]):
        print("  %-20s %d" % (s, n))
    print("-" * 60)
    if errors:
        print("!!! 问题汇总:")
        for k, v in sorted(errors.items(), key=lambda x: -len(x[1])):
            print("  [%s] %d 例: %s" % (k, len(v), "; ".join(v[:3])))
    else:
        print("格式校验: 全部通过")
    if dup_lines:
        print("!!! 完全重复回复 %d 例: %s" % (len(dup_lines), dup_lines[:3]))
    if dup_open:
        print("!! 重复开头(前10字) %d 组, 最多: %s" % (len(dup_open), sorted(dup_open, key=lambda x: -x[1])[:5]))
    print("=" * 60)

    if do_merge:
        import random
        random.Random(42).shuffle(all_samples)  # 打乱批次顺序，避免训练时按场景成块出现
        out = os.path.join(ROOT, "train.jsonl")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            for obj in all_samples:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        print("已合并 -> %s (%d 条)" % (out, len(all_samples)))


if __name__ == "__main__":
    main()
