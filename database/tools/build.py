#!/usr/bin/env python3
"""Build the one merged catgirl SFT corpus from the archived sources.

    python tools/build.py                      # heuristic token estimate
    python tools/build.py --tokenizer /path/to/Qwen3.5-4B-Base

Sources (archive/, never edited in place):
  archive/a_batch_*.jsonl                  -> 小咪 backstory set      (source=catgirl_dataset)
  archive/b_batch_*.jsonl + b_samples_5    -> apartment set           (source=qwen_catgirl_ft)
  archive/nekoqa_10k.json                  -> catgirl Q&A, cleaned    (source=nekoqa)

Every surviving row gets the same system prompt, Chinese scene label, strict
human/gpt alternation, 1-6 gpt turns and 50-200 char replies.  NekoQA is the only
single-turn source; its bracketed/asterisk stage directions are stripped and the
"主人/宝宝" address is rewritten into the shared persona before filtering.
"""

from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import random
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(ROOT, "archive")
SYSTEM_FILE = os.path.join(ROOT, "system_prompt.txt")
OUT_TRAIN = os.path.join(ROOT, "train.jsonl")
OUT_SAMPLES = os.path.join(ROOT, "samples_5.jsonl")
OUT_REPORT = os.path.join(ROOT, "REPORT.json")
COT_FILE = os.path.join(ROOT, "cot", "cot.jsonl")

SCENES = {
    "起床", "做饭吃饭", "家务", "通勤", "上班上课", "加班", "逛街", "看电影",
    "生病照顾", "吵架和好", "睡前聊天", "微信短聊", "接梗日常", "校园回忆",
    "周末出游", "游戏爱好", "纪念日礼物", "学习考试", "天气雨天", "日常问答",
}

SCENE_MAP = {
    "起床": "起床", "做饭吃饭": "做饭吃饭", "家务": "家务", "通勤": "通勤",
    "上班上课": "上班上课", "加班": "加班", "逛街": "逛街", "看电影": "看电影",
    "生病照顾": "生病照顾", "吵架冷战": "吵架和好", "和好": "吵架和好",
    "睡前聊天": "睡前聊天", "微信短聊": "微信短聊", "接梗日常": "接梗日常",
    "大学生活": "校园回忆", "高一回忆": "校园回忆", "高二回忆": "校园回忆",
    "高三备考": "校园回忆",
    "morning_wakeup": "起床", "cooking_meal": "做饭吃饭", "housework": "家务",
    "commute": "通勤", "work_school": "上班上课", "overtime": "加班",
    "shopping": "逛街", "movie_tv": "看电影", "illness_care": "生病照顾",
    "quarrel_reconcile": "吵架和好", "bedtime": "睡前聊天",
    "weekend_outing": "周末出游", "gaming_hobby": "游戏爱好",
    "anniversary_gift": "纪念日礼物", "study_exam": "学习考试",
    "weather_rain": "天气雨天",
}

# Kept narrow on purpose: 脚本/扮演/模型 alone are legitimate in real conversation
# (回滚脚本、话剧社扮演、手办模型), only the out-of-character forms are rejected.
BANNED = (
    "人工智能", "语言模型", "大模型", "数据集", "微调", "OpenAI", "Qwen",
    "千问", "通义", "角色扮演", "系统提示", "作为一只猫娘",
)
BANNED_RE = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])")

META_QUESTION = re.compile(
    r"如何|怎样|怎么才能|该怎么做|说一说|介绍一下|描述一下|是什么体验|是什么感觉|是什么"
)

# Bracket/parenthesis and asterisk stage directions, including the [placeholder]
# forms that NekoQA uses for its own name.
ACTION = re.compile(
    r"[（(【\[][^）)】\]\n]{0,80}[）)】\]]"
    r"|\*[^*\n]{1,80}\*"
    r"|＊[^＊\n]{1,80}＊"
)

CAT_WORDS = ("喵", "本喵", "咱")

# NekoQA occasionally lets another catgirl name leak into the reply; the merged
# persona is 小咪, so self-introductions and self-references are dropped instead
# of being renamed blindly (小雪/小美/小白 also appear as weather or other people).
NAME_LEAK = re.compile(
    r"莉莉|(?:我是|我叫|人家叫|名字叫|叫做|让|叫)"
    r"(?:你的)?(?:猫娘)?(?:小雪|小橘|咪咪|小铃|小美|小可|小爱|小月|糖糖|果果|团团|小雅|小樱)"
)


def load_system():
    with open(SYSTEM_FILE, encoding="utf-8") as f:
        return f.read().strip()


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def tidy(text, comma_join=False):
    """Strip action spans and whitespace; optionally join wrapped lines with a comma."""
    text = ACTION.sub("", text)
    if comma_join:
        text = re.sub(r"\s*\n+\s*", "，", text)
    else:
        text = re.sub(r"\s*\n+\s*", "", text)
    text = re.sub(r"[ \t\u3000]+", "", text)
    text = re.sub(r"，{2,}", "，", text)
    return text.strip("， ")


def tidy_human(text):
    return re.sub(r"\s+", " ", text).strip()


def tidy_nekoqa_reply(text):
    text = tidy(text, comma_join=True)
    text = text.replace("主人", "你").replace("宝宝", "本喵")
    text = re.sub(r"你你+", "你", text)
    # NekoQA's Japanese-translation tic; only drop it in sentence-final position,
    # including the "的说喵~" variant where a meow follows the particle.
    text = re.sub(r"的说(?=喵?[，。！？~～…]|喵?\.|$)", "", text)
    return text.strip("， ")


def tidy_nekoqa_instruction(text):
    text = tidy(text, comma_join=True)
    text = re.sub(r"^(宝宝|主人)[，,]\s*", "", text)
    text = re.sub(r"^(?:用户[:：]\s*)?(?:初始问题[:：]\s*)?", "", text)
    text = re.sub(r"^(?:问题|提问)[:：]\s*", "", text)
    text = text.replace("主人", "你").replace("宝宝", "你")
    return re.sub(r"你你+", "你", text).strip("， ")


def banned_hit(*texts):
    for text in texts:
        if BANNED_RE.search(text) or any(w in text for w in BANNED):
            return True
    return False


def split_turns(conv):
    turns = [(m["from"], m["value"]) for m in conv if m["from"] != "system"]
    roles = [r for r, _ in turns]
    if not turns or roles[0] != "human" or roles[-1] != "gpt":
        return None
    if any(a == b for a, b in zip(roles, roles[1:])):
        return None
    return turns


def iter_ab(source_name, pattern, scene_key="scene"):
    for path in sorted(glob.glob(pattern)):
        for row in read_jsonl(path):
            scene = SCENE_MAP.get(row.get(scene_key))
            turns = split_turns(row.get("conversations") or [])
            if scene is None or turns is None:
                yield source_name, row.get(scene_key), None
                continue
            yield source_name, scene, turns


def collect(system):
    rows = []
    drops = collections.defaultdict(collections.Counter)
    raw_counts = collections.Counter()

    # A: 小咪 backstory set.
    for source, scene, turns in iter_ab(
            "catgirl_dataset",
            os.path.join(SOURCES, "a_batch_*.jsonl")):
        raw_counts[source] += 1
        if turns is None:
            drops[source]["structure"] += 1
            continue
        cleaned = []
        for role, value in turns:
            if role == "gpt":
                value = tidy(value)
            else:
                value = tidy_human(value)
            if not value:
                cleaned = None
                break
            cleaned.append((role, value))
        if cleaned is None:
            drops[source]["empty"] += 1
            continue
        gpt = [v for r, v in cleaned if r == "gpt"]
        if any(not (50 <= len(v) <= 200) for v in gpt):
            drops[source]["length"] += 1
            continue
        if banned_hit(*(v for _, v in cleaned)):
            drops[source]["banned"] += 1
            continue
        rows.append((source, scene, cleaned))

    # B: apartment set.  The five hand-picked samples live in b_samples_5 and are
    # not duplicated in the 28 batches, so both globs are required for the full 565.
    b_paths = (sorted(glob.glob(os.path.join(SOURCES, "b_batch_*.jsonl")))
               + [os.path.join(SOURCES, "b_samples_5.jsonl")])
    for pattern in b_paths:
        for source, scene, turns in iter_ab("qwen_catgirl_ft", pattern):
            raw_counts[source] += 1
            if turns is None:
                drops[source]["structure"] += 1
                continue
            cleaned = []
            for role, value in turns:
                value = tidy(value) if role == "gpt" else tidy_human(value)
                if not value:
                    cleaned = None
                    break
                cleaned.append((role, value))
            if cleaned is None:
                drops[source]["empty"] += 1
                continue
            gpt = [v for r, v in cleaned if r == "gpt"]
            if any(not (50 <= len(v) <= 200) for v in gpt):
                drops[source]["length"] += 1
                continue
            if banned_hit(*(v for _, v in cleaned)):
                drops[source]["banned"] += 1
                continue
            rows.append((source, scene, cleaned))

    # C: NekoQA, cleaned to the same chat shape.
    source = "nekoqa"
    with open(os.path.join(SOURCES, "nekoqa_10k.json"), encoding="utf-8") as f:
        raw_nekoqa = json.load(f)
    for item in raw_nekoqa:
        raw_counts[source] += 1
        raw_instr = item.get("instruction", "")
        # 主人 is how the NekoQA catgirl addresses the user; if it appears on the
        # user side the row is written in the wrong voice.  Same for 本少爷/本小姐.
        if any(w in raw_instr for w in ("主人", "本少爷", "本小姐")):
            drops[source]["role_voice"] += 1
            continue
        if any(w in item.get("output", "") for w in ("本少爷", "本小姐")):
            drops[source]["role_voice"] += 1
            continue
        if NAME_LEAK.search(raw_instr) or NAME_LEAK.search(item.get("output", "")):
            drops[source]["name_leak"] += 1
            continue
        instr = tidy_nekoqa_instruction(raw_instr)
        reply = tidy_nekoqa_reply(item.get("output", ""))
        if not instr or not reply:
            drops[source]["empty"] += 1
            continue
        if not (50 <= len(reply) <= 200):
            drops[source]["length"] += 1
            continue
        if not (10 <= len(instr) <= 60):
            drops[source]["instr_length"] += 1
            continue
        if META_QUESTION.search(instr):
            drops[source]["meta_question"] += 1
            continue
        # the user must not speak in the catgirl's voice after replacement
        if any(w in instr for w in ("喵", "咱", "本喵")):
            drops[source]["user_cat_voice"] += 1
            continue
        if banned_hit(instr, reply):
            drops[source]["banned"] += 1
            continue
        if any(c in instr + reply for c in "[]＊*（）()【】"):
            drops[source]["artifact"] += 1
            continue
        rows.append((source, "日常问答", [("human", instr), ("gpt", reply)]))

    # Exact duplicate dialogues across all sources.
    seen = set()
    unique = []
    for source, scene, turns in rows:
        sig = tuple(turns)
        if sig in seen:
            drops[source]["duplicate"] += 1
            continue
        seen.add(sig)
        unique.append((source, scene, turns))

    random.Random(42).shuffle(unique)
    out = []
    for i, (source, scene, turns) in enumerate(unique, 1):
        conv = [{"from": "system", "value": system}]
        conv += [{"from": role, "value": value} for role, value in turns]
        out.append({
            "id": "cg_%04d" % i,
            "source": source,
            "scene": scene,
            "conversations": conv,
        })
    return out, dict(drops), dict(raw_counts)


def apply_cot(rows, path):
    """Attach the final-turn hidden monologue as a top-level `cot` field."""
    cot = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rid, text = obj.get("id"), obj.get("cot", "").strip()
            if not rid or not isinstance(text, str):
                raise SystemExit("bad cot line: %s" % obj)
            if rid in cot:
                raise SystemExit("duplicate cot id: %s" % rid)
            cot[rid] = text
    ids = [r["id"] for r in rows]
    missing = [rid for rid in ids if rid not in cot]
    extra = [rid for rid in cot if rid not in set(ids)]
    if missing or extra:
        raise SystemExit("cot id mismatch: missing=%s extra=%s"
                         % (missing[:5], extra[:5]))
    out = []
    for row in rows:
        text = cot[row["id"]]
        if not (30 <= len(text) <= 60):
            raise SystemExit("cot length %d at %s" % (len(text), row["id"]))
        if "\n" in text or ACTION.search(text):
            raise SystemExit("cot artifact at %s" % row["id"])
        if banned_hit(text):
            raise SystemExit("cot banned word at %s" % row["id"])
        merged = {k: row[k] for k in ("id", "source", "scene")}
        merged["cot"] = text
        merged["conversations"] = row["conversations"]
        out.append(merged)
    return out


def validate(rows, system):
    problems = []
    for row in rows:
        conv = row["conversations"]
        if conv[0]["from"] != "system" or conv[0]["value"] != system:
            problems.append((row["id"], "system"))
            continue
        if sum(1 for m in conv if m["from"] == "system") != 1:
            problems.append((row["id"], "multi-system"))
        if any(set(m) != {"from", "value"} for m in conv):
            problems.append((row["id"], "keys"))
        roles = [m["from"] for m in conv[1:]]
        if not roles or roles[0] != "human" or roles[-1] != "gpt":
            problems.append((row["id"], "ends"))
        if any(a == b for a, b in zip(roles, roles[1:])):
            problems.append((row["id"], "alternation"))
        pairs = roles.count("gpt")
        if not (1 <= pairs <= 6):
            problems.append((row["id"], "turns"))
        if row["scene"] not in SCENES:
            problems.append((row["id"], "scene"))
        if "cot" in row:
            text = row["cot"]
            if not (30 <= len(text) <= 60) or "\n" in text:
                problems.append((row["id"], "cot"))
            if ACTION.search(text) or banned_hit(text):
                problems.append((row["id"], "cot-artifact"))
        for m in conv[1:]:
            text = m["value"]
            if not text.strip():
                problems.append((row["id"], "empty"))
            if m["from"] == "gpt":
                if not (50 <= len(text) <= 200):
                    problems.append((row["id"], "length"))
                if ACTION.search(text):
                    problems.append((row["id"], "stage-direction"))
                if text != tidy(text) or any(c in text for c in "[]＊*"):
                    problems.append((row["id"], "artifact"))
            if banned_hit(text):
                problems.append((row["id"], "banned"))
    if problems:
        raise SystemExit("validation failed: %s" % problems[:10])


def token_stats(texts, tokenizer_dir):
    if not tokenizer_dir:
        chars = sum(len(t) for t in texts)
        return {"mode": "estimate(chars*0.72)", "tokens": int(chars * 0.72)}
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True)
    encoded = tok(texts, add_special_tokens=False, verbose=False)["input_ids"]
    return {"mode": os.path.basename(tokenizer_dir.rstrip("/")),
            "tokens": sum(len(x) for x in encoded)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer", default=None,
                    help="local HF tokenizer dir for exact token counts")
    ap.add_argument("--cot", default=None,
                    help="CoT JSONL; defaults to cot/cot.jsonl when present")
    ap.add_argument("--no-cot", action="store_true", help="build without CoT")
    args = ap.parse_args()

    system = load_system()
    rows, drops, raw_counts = collect(system)
    cot_path = None if args.no_cot else (
        args.cot or (COT_FILE if os.path.exists(COT_FILE) else None))
    if cot_path:
        rows = apply_cot(rows, cot_path)
    validate(rows, system)

    with open(OUT_TRAIN, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    daily = re.compile(r"^困啦|^抱|^陪我|^晚安|^早安|今天的云朵像")
    picked = []
    for scene in ("起床", "做饭吃饭", "吵架和好", "睡前聊天"):
        sample = next((r for r in rows if r["scene"] == scene), None)
        if sample:
            picked.append(sample)
    sample = (next((r for r in rows if r["source"] == "nekoqa"
                    and daily.search(r["conversations"][1]["value"])), None)
              or next((r for r in rows if r["source"] == "nekoqa"), None))
    if sample:
        picked.append(sample)
    for row in rows:
        if len(picked) >= 5:
            break
        if row not in picked:
            picked.append(row)
    with open(OUT_SAMPLES, "w", encoding="utf-8", newline="\n") as f:
        for row in picked[:5]:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    gpt = [m["value"] for r in rows for m in r["conversations"] if m["from"] == "gpt"]
    turns = collections.Counter(
        sum(1 for m in r["conversations"] if m["from"] == "gpt") for r in rows)
    by_source = collections.Counter(r["source"] for r in rows)
    by_scene = collections.Counter(r["scene"] for r in rows)
    jsonl_lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
    dialogue = ["\n".join(m["value"] for m in r["conversations"]) for r in rows]

    whole = token_stats(jsonl_lines, args.tokenizer)
    content = token_stats(dialogue, args.tokenizer)
    cots = [r["cot"] for r in rows if "cot" in r]
    with_cot = content
    if cots:
        cot_tokens = token_stats(
            ["<think>\n" + c + "\n</think>\n\n" for c in cots], args.tokenizer)
        with_cot = {"mode": content["mode"],
                    "tokens": content["tokens"] + cot_tokens["tokens"]}
    report = {
        "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "system_chars": len(system),
        "samples": len(rows),
        "gpt_replies": len(gpt),
        "cot": {
            "count": len(cots),
            "min": min((len(c) for c in cots), default=0),
            "avg": round(sum(len(c) for c in cots) / max(1, len(cots)), 1),
            "max": max((len(c) for c in cots), default=0),
            "by_source": dict(collections.Counter(
                r["source"] for r in rows if "cot" in r)),
        },
        "gpt_len": {
            "min": min(len(x) for x in gpt),
            "avg": round(sum(len(x) for x in gpt) / len(gpt), 1),
            "max": max(len(x) for x in gpt),
        },
        "cat_word_reply_share": round(
            sum(any(w in x for w in CAT_WORDS) for x in gpt) / len(gpt), 4),
        "style_tic_replies": {
            "deshuo": sum("的说" in x for x in gpt),
            "bens_miao": sum("本喵" in x for x in gpt),
        },
        "turns": {str(k): v for k, v in sorted(turns.items())},
        "by_source": dict(by_source),
        "by_scene": dict(sorted(by_scene.items(), key=lambda kv: -kv[1])),
        "raw": raw_counts,
        "dropped": drops,
        "keep": {k: len([r for r in rows if r["source"] == k]) for k in by_source},
        "tokens_whole_jsonl": whole,
        "tokens_dialogue_text": content,
        "tokens_dialogue_with_cot": with_cot,
        "seed": 42,
    }
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("rows=%d  gpt=%d  cot=%d  len=%d-%d(avg %.1f)  meow_share=%.1f%%" % (
        report["samples"], report["gpt_replies"], report["cot"]["count"],
        report["gpt_len"]["min"], report["gpt_len"]["max"],
        report["gpt_len"]["avg"], 100 * report["cat_word_reply_share"]))
    print("by_source:", dict(by_source))
    print("by_scene:", dict(by_scene))
    for src in ("catgirl_dataset", "qwen_catgirl_ft", "nekoqa"):
        print("  %-18s raw=%d keep=%d drop=%s" % (
            src, raw_counts.get(src, 0), by_source.get(src, 0), drops.get(src, {})))
    print("tokens: whole=%s content=%s" % (whole, content))


if __name__ == "__main__":
    import sys

    if "--from" in sys.argv and "accepted" in sys.argv:
        from build_wechat import main as build_wechat_main

        build_wechat_main()
    else:
        main()
