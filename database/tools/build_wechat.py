from __future__ import annotations
import collections, json, random, re

SCENES = {"起床","做饭吃饭","家务","通勤","上班上课","加班","逛街","看电影",
          "生病照顾","吵架和好","睡前聊天","微信短聊","接梗日常","校园回忆",
          "周末出游","游戏爱好","纪念日礼物","学习考试","天气雨天","日常问答"}
BANNED = ("人工智能","语言模型","大模型","数据集","微调","OpenAI","Qwen","千问",
          "通义","角色扮演","系统提示","作为一只猫娘","主人","气泡","分隔符")
BANNED_RE = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])")
ACTION = re.compile(r"[（(【\[][^）)】\]\n]{0,80}[）)】\]]|\*[^*\n]{1,80}\*|＊[^＊\n]{1,80}＊")
CAT_WORDS = ("喵","本喵","咱")
META = ("气泡","分隔符","分几条")

def bad_text(s):
    return bool(BANNED_RE.search(s) or any(w in s for w in BANNED) or ACTION.search(s))

def validate_bubbles(bubbles, profile="short"):
    errs = []
    if not isinstance(bubbles, list) or not bubbles:
        return ["empty"]
    if profile == "short" and not 1 <= len(bubbles) <= 3:
        errs.append("count")
    if profile == "long" and not 2 <= len(bubbles) <= 4:
        errs.append("count")
    total, seen = 0, set()
    for b in bubbles:
        if not isinstance(b, str) or not b or b != b.strip():
            errs.append("string"); continue
        if "\n\n" in b:
            errs.append("double_newline")
        if "\r" in b:
            errs.append("cr")
        limit = 18 if profile == "short" else 60
        if not 2 <= len(b) <= limit:
            errs.append("len")
        if b in seen:
            errs.append("dup")
        seen.add(b)
        if b[-1] in "，,、：:；;":
            errs.append("dangling")
        if bad_text(b) or any(c in b for c in "[]＊*（）()【】"):
            errs.append("artifact")
        total += len(b)
    if profile == "short" and not 2 <= total <= 60:
        errs.append("total")
    if profile == "long" and not 60 <= total <= 200:
        errs.append("total")
    return errs

def validate_human(h):
    errs = []
    if not isinstance(h, str) or not 3 <= len(h) <= 30 or "\n" in h:
        errs.append("len")
    if isinstance(h, str):
        if bad_text(h) or any(w in h for w in CAT_WORDS):
            errs.append("voice")
        if any(c in h for c in "[]＊*（）()【】"):
            errs.append("artifact")
    return errs

def validate_callback(turns, i, ref):
    if ref is None:
        return []
    if not isinstance(ref, dict):
        return ["shape"]
    t, key = ref.get("turn"), ref.get("key")
    if not isinstance(t, int) or not isinstance(key, str):
        return ["shape"]
    if not (1 <= t <= i) or not (1 <= len(key) <= 8):
        return ["turn/key"]
    prev = turns[t - 1]
    prev_text = prev.get("human", "") + "\n" + "\n".join(prev.get("bubbles", []))
    cur_text = "\n".join(turns[i].get("bubbles", []))
    if key not in prev_text or key not in cur_text:
        return ["key_missing"]
    return []

def source_turns(src):
    return [(m["from"], m["value"]) for m in src["conversations"] if m["from"] != "system"]

def validate_rewrite(out, src):
    errs = []
    status = out.get("status")
    if status not in ("ok", "skip"):
        return ["status"]
    if status == "skip":
        if not out.get("reason"):
            errs.append("skip_reason")
        return errs
    st = source_turns(src)
    src_humans = [v for r, v in st if r == "human"]
    src_gpts = [v for r, v in st if r == "gpt"]
    turns = out.get("turns")
    if not isinstance(turns, list) or len(turns) != len(src_gpts):
        return ["turns"]
    for idx, (turn, _sg) in enumerate(zip(turns, src_gpts)):
        if not isinstance(turn, dict):
            errs.append((idx, "type")); continue
        errs += [(idx, e) for e in validate_bubbles(turn.get("bubbles"), turn.get("profile", "short"))]
        if "human" in turn:
            if not turn.get("user_changed"):
                errs.append((idx, "human_without_flag"))
            errs += [(idx, e) for e in validate_human(turn["human"])]
        elif turn.get("user_changed"):
            errs.append((idx, "flag_without_human"))
    return errs

def validate_new(out, seed):
    turns = out.get("turns")
    if not isinstance(turns, list) or not 6 <= len(turns) <= 8:
        return ["turns"]
    errs, cbs = [], []
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict):
            errs.append((i, "type")); continue
        errs += [(i, e) for e in validate_human(turn.get("human"))]
        errs += [(i, e) for e in validate_bubbles(turn.get("bubbles"), turn.get("profile", "short"))]
        ref = turn.get("callback_ref")
        if ref:
            cbs.append((i, ref))
            errs += [(i, e) for e in validate_callback(turns, i, ref)]
    if not 1 <= len(cbs) <= 2:
        errs.append(("callbacks", len(cbs)))
    if not any(i >= 2 for i, _ in cbs):
        errs.append("no_callback_after_turn3")
    return errs

def apply_fixes(rows, fixes):
    by_id = {r["origin_id"]: r for r in rows}
    for f in fixes:
        r = by_id.get(f["origin_id"])
        if r is None:
            raise ValueError(f"fix target missing: {f['origin_id']}")
        idx = f["turn"] - 1
        if not 0 <= idx < len(r["turns"]):
            raise ValueError(f"fix turn out of range: {f}")
        turn = r["turns"][idx]
        field = f["field"]
        if field not in ("bubbles", "human"):
            raise ValueError(f"bad fix field: {f}")
        if turn.get(field) != f["old"]:
            raise ValueError(f"fix old mismatch: {f['origin_id']} turn {f['turn']}")
        turn[field] = f["new"]
        if field == "human":
            turn["user_changed"] = True

def assemble_rewrite(out, src):
    st = source_turns(src)
    src_humans = [v for r, v in st if r == "human"]
    turns = []
    for idx, ot in enumerate(out["turns"]):
        human = ot.get("human", src_humans[idx])
        turns.append({"human": human, "gpt": "\n\n".join(ot["bubbles"]),
                      "_bubbles": ot["bubbles"], "profile": ot.get("profile", "short")})
    return {"origin_id": out["origin_id"], "source": src["source"],
            "scene": src["scene"], "turns": turns}

def assemble_new(out, seed):
    turns = []
    for ot in out["turns"]:
        turns.append({"human": ot["human"], "gpt": "\n\n".join(ot["bubbles"]),
                      "_bubbles": ot["bubbles"], "profile": ot.get("profile", "short"),
                      "callback_ref": ot.get("callback_ref")})
    return {"origin_id": out["origin_id"], "source": "distill_new",
            "scene": seed["scene"], "turns": turns,
            "_callback_refs": [t["callback_ref"] for t in turns if t.get("callback_ref")]}

def validate_cot(text):
    errs = []
    if not isinstance(text, str) or not 8 <= len(text) <= 40 or "\n" in text:
        errs.append("len")
    if isinstance(text, str):
        if bad_text(text) or any(w in text for w in META) or any(c in text for c in "[]＊*（）()【】"):
            errs.append("artifact")
    return errs

def attach_cot(rows, cot, required=True):
    for r in rows:
        text = cot.get(r["origin_id"])
        if not text:
            if required:
                raise ValueError(f"missing cot: {r['origin_id']}")
            continue
        errs = validate_cot(text)
        if errs:
            raise ValueError(f"bad cot {r['origin_id']}: {errs}")
        r["cot"] = text

def finalize(rows, system):
    out = []
    for r in rows:
        conv = [{"from": "system", "value": system}]
        for t in r["turns"]:
            conv.append({"from": "human", "value": t["human"]})
            conv.append({"from": "gpt", "value": t["gpt"]})
        out.append({"origin_id": r["origin_id"], "source": r["source"], "scene": r["scene"],
                    "cot": r.get("cot"), "conversations": conv,
                    "_bubbles": [t["_bubbles"] for t in r["turns"]],
                    "_profiles": [t.get("profile", "short") for t in r["turns"]],
                    "_callback_refs": r.get("_callback_refs", [])})
    return out

def validate_final(rows, system):
    errs = []
    for row in rows:
        conv = row["conversations"]
        if conv[0]["from"] != "system" or conv[0]["value"] != system:
            errs.append((row["origin_id"], "system"))
        roles = [m["from"] for m in conv[1:]]
        if not roles or roles[0] != "human" or roles[-1] != "gpt" or any(a == b for a, b in zip(roles, roles[1:])):
            errs.append((row["origin_id"], "roles"))
        if not 1 <= roles.count("gpt") <= 8:
            errs.append((row["origin_id"], "turns"))
        if row["scene"] not in SCENES:
            errs.append((row["origin_id"], "scene"))
        gpts = [m["value"] for m in conv if m["from"] == "gpt"]
        if len(gpts) != len(row["_bubbles"]):
            errs.append((row["origin_id"], "bubble_count"))
        for value, bubbles in zip(gpts, row["_bubbles"]):
            if value != "\n\n".join(bubbles) or value.split("\n\n") != bubbles:
                errs.append((row["origin_id"], "join"))
    return errs

PRIORITY = {"distill_new": 0, "qwen_catgirl_ft": 1, "catgirl_dataset": 2, "nekoqa": 3}
def dedupe(rows):
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: (PRIORITY.get(x["source"], 9), x["origin_id"])):
        sig = tuple((t["human"], t["gpt"]) for t in r["turns"])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out

def downsample_nekoqa(rows, cap=0.40):
    if cap >= 1:
        return rows
    neko = [r for r in rows if r["source"] == "nekoqa"]
    other = [r for r in rows if r["source"] != "nekoqa"]
    if not neko or len(neko) / len(rows) <= cap:
        return rows
    keep_n = min(len(neko), int(cap * len(other) / (1 - cap)))
    keep = {r["origin_id"] for r in random.Random(42).sample(sorted(neko, key=lambda x: x["origin_id"]), keep_n)}
    return [r for r in rows if r["source"] != "nekoqa" or r["origin_id"] in keep]

def assign_ids(rows, seed=42):
    random.Random(seed).shuffle(rows)
    if len(rows) > 9999:
        raise ValueError("more than 9999 rows")
    id_map = {}
    for i, r in enumerate(rows, 1):
        new_id = "cg_%04d" % i
        id_map[new_id] = r["origin_id"]
        r["id"] = new_id
    return id_map

def build_data(legacy, seeds, rewrite_out, new_out, fixes, cot, system, cap=0.40,
               cot_required=True, long_cap=0.05, drop_missing_cot=False,
               drop_ids=None):
    apply_fixes(rewrite_out + new_out, fixes)
    rows = []
    for out in rewrite_out:
        src = legacy.get(out["origin_id"])
        if src is None:
            raise ValueError(f"unknown origin_id {out['origin_id']}")
        errs = validate_rewrite(out, src)
        if errs:
            raise ValueError(f"rewrite {out['origin_id']}: {errs[:5]}")
        if out["status"] == "ok":
            rows.append(assemble_rewrite(out, src))
    for out in new_out:
        seed = seeds.get(out["seed_id"])
        if seed is None:
            raise ValueError(f"unknown seed {out['seed_id']}")
        errs = validate_new(out, seed)
        if errs:
            raise ValueError(f"new {out['origin_id']}: {errs[:5]}")
        rows.append(assemble_new(out, seed))
    if drop_missing_cot:
        before = len(rows)
        rows = [r for r in rows if r["origin_id"] in cot]
        print("[build] dropped %d rows missing CoT" % (before - len(rows)))
    if drop_ids:
        before = len(rows)
        rows = [r for r in rows if r["origin_id"] not in drop_ids]
        print("[build] dropped %d rows by --drop-ids" % (before - len(rows)))
    rows = dedupe(rows)
    rows = downsample_nekoqa(rows, cap)
    long_rows = [r for r in rows if any(t.get("profile") == "long" for t in r["turns"])]
    if long_cap < 1.0 and long_rows:
        max_long = int(long_cap * len(rows))
        if len(long_rows) > max_long:
            keep = {r["origin_id"] for r in sorted(
                long_rows, key=lambda r: r["origin_id"])[:max_long]}
            rows = [r for r in rows
                    if r not in long_rows or r["origin_id"] in keep]
    attach_cot(rows, cot, required=cot_required)
    final = finalize(rows, system)
    errs = validate_final(final, system)
    if errs:
        raise ValueError(f"final: {errs[:5]}")
    id_map = assign_ids(final)
    return final, id_map


# ---------------------------------------------------------------- I/O / CLI

import argparse
import glob
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM = os.path.join(ROOT, "system_prompt.txt")
LEGACY = os.path.join(ROOT, "distill", "source", "legacy_train.jsonl")
ACCEPTED = os.path.join(ROOT, "distill", "accepted")
SEEDS = os.path.join(ROOT, "distill", "seeds", "all_scenes.jsonl")
FIXES = os.path.join(ROOT, "distill", "review", "fixes.jsonl")
COT = os.path.join(ROOT, "distill", "cot.jsonl")
OUT = os.path.join(ROOT, "train.jsonl")
REPORT = os.path.join(ROOT, "REPORT.json")
ID_MAP = os.path.join(ROOT, "distill", "manifests", "final_id_map.json")
SAMPLES = os.path.join(ROOT, "samples_5.jsonl")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path, rows):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def write_json(path, obj):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_legacy(path):
    return {r["id"]: r for r in read_jsonl(path)}


def load_seeds(path):
    return {r["seed_id"]: r for r in read_jsonl(path)}


def load_accepted(dir_path):
    rewrite, new = [], []
    for path in sorted(glob.glob(os.path.join(dir_path, "rewrite*.jsonl"))):
        rewrite.extend(read_jsonl(path))
    for path in sorted(glob.glob(os.path.join(dir_path, "new*.jsonl"))):
        new.extend(read_jsonl(path))
    return rewrite, new


def load_fixes(path):
    return list(read_jsonl(path)) if os.path.exists(path) else []


def load_cot(path):
    return {r["id"]: r["cot"] for r in read_jsonl(path)} if os.path.exists(path) else {}


def is_emoji(ch):
    return ord(ch) >= 0x1F000 or ch in "❤♥"


def make_report(final, id_map, system, prompt_version, legacy_path, user_changed=0):
    per_turn = [turn for row in final for turn in row["_bubbles"]]
    bubbles = [bubble for turn in per_turn for bubble in turn]
    lengths = [len(bubble) for bubble in bubbles]
    turn_lengths = [len("\n\n".join(turn)) for turn in per_turn]
    bubble_hist = collections.Counter(len(turn) for turn in per_turn)
    cot = [row["cot"] for row in final if row.get("cot")]
    legacy_sha = None
    if os.path.exists(legacy_path):
        legacy_sha = hashlib.sha256(open(legacy_path, "rb").read()).hexdigest()
    return {
        "mode": "accepted",
        "prompt_version": prompt_version,
        "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "system_chars": len(system),
        "legacy_sha256": legacy_sha,
        "samples": len(final),
        "gpt_replies": sum(len(row["_bubbles"]) for row in final),
        "assistant_turns": len(per_turn),
        "bubbles": len(bubbles),
        "bubble_count": {str(k): v for k, v in sorted(bubble_hist.items())},
        "bubble_len": {
            "min": min(lengths, default=0),
            "avg": round(sum(lengths) / max(1, len(lengths)), 1),
            "max": max(lengths, default=0),
        },
        "turn_len": {
            "min": min(turn_lengths, default=0),
            "avg": round(sum(turn_lengths) / max(1, len(turn_lengths)), 1),
            "max": max(turn_lengths, default=0),
        },
        "single_bubble_share": round(bubble_hist.get(1, 0) / max(1, len(per_turn)), 4),
        "multi_bubble_share": round(
            sum(v for k, v in bubble_hist.items() if k > 1) / max(1, len(per_turn)), 4),
        "emoji_turn_share": round(
            sum(1 for turn in per_turn if any(is_emoji(ch) for b in turn for ch in b))
            / max(1, len(per_turn)), 4),
        "question_turn_share": round(
            sum(1 for turn in per_turn if re.search(r"[？?]\s*$|[吗呢嘛]\s*$", turn[-1]))
            / max(1, len(per_turn)), 4),
        "cat_turn_share": round(
            sum(1 for turn in per_turn if any(w in b for b in turn for w in CAT_WORDS))
            / max(1, len(per_turn)), 4),
        "long_turns": sum(1 for row in final for p in row.get("_profiles", []) if p == "long"),
        "long_rows": sum(1 for row in final if "long" in row.get("_profiles", [])),
        "bens_miao_share": round(
            sum(1 for turn in per_turn if any("本喵" in b for b in turn))
            / max(1, len(per_turn)), 4),
        "callback": {
            "sessions_with": sum(1 for row in final if row.get("_callback_refs")),
            "refs": sum(len(row.get("_callback_refs", [])) for row in final),
        },
        "user_changed": user_changed,
        "cot": {
            "count": len(cot),
            "min": min((len(x) for x in cot), default=0),
            "avg": round(sum(len(x) for x in cot) / max(1, len(cot)), 1),
            "max": max((len(x) for x in cot), default=0),
        },
        "by_source": dict(collections.Counter(row["source"] for row in final)),
        "by_scene": dict(sorted(collections.Counter(row["scene"] for row in final).items(),
                                key=lambda kv: -kv[1])),
        "turns": {str(k): v for k, v in sorted(
            collections.Counter(len(row["_bubbles"]) for row in final).items())},
        "id_map_size": len(id_map),
        "seed": 42,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_mode", choices=("accepted",), default="accepted")
    ap.add_argument("--legacy-source", default=LEGACY)
    ap.add_argument("--accepted-dir", default=ACCEPTED)
    ap.add_argument("--seeds", default=SEEDS)
    ap.add_argument("--fixes", default=FIXES)
    ap.add_argument("--cot", default=COT)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--samples-out", default=SAMPLES)
    ap.add_argument("--prompt-version", default="wechat-v1.3")
    ap.add_argument("--long-cap", type=float, default=0.05,
                    help="max share of rows containing a long turn (1.0 disables)")
    ap.add_argument("--keep-all-nekoqa", action="store_true")
    ap.add_argument("--drop-missing-cot", action="store_true",
                    help="drop candidate rows without CoT instead of failing")
    ap.add_argument("--drop-ids", default=None,
                    help="file with one origin_id per line to exclude from the build")
    ap.add_argument("--no-cot", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    system = open(SYSTEM, encoding="utf-8").read().strip()
    legacy = load_legacy(args.legacy_source)
    seeds = load_seeds(args.seeds)
    rewrite, new = load_accepted(args.accepted_dir)
    fixes = load_fixes(args.fixes)
    cot = load_cot(args.cot)
    if not rewrite and not new:
        raise SystemExit("no accepted rows found in %s" % args.accepted_dir)

    drop_ids = set()
    if args.drop_ids:
        with open(args.drop_ids, encoding="utf-8") as f:
            drop_ids = {line.strip() for line in f if line.strip()}
    user_changed = sum(
        1 for row in rewrite for turn in row.get("turns", []) if turn.get("user_changed"))
    final, id_map = build_data(
        legacy, seeds, rewrite, new, fixes, cot, system,
        cap=1.0 if args.keep_all_nekoqa else 0.40,
        cot_required=not args.no_cot,
        long_cap=args.long_cap,
        drop_missing_cot=args.drop_missing_cot,
        drop_ids=drop_ids,
    )
    report = make_report(final, id_map, system, args.prompt_version,
                         args.legacy_source, user_changed)
    out_rows = []
    for row in final:
        out = {"id": row["id"], "source": row["source"], "scene": row["scene"]}
        if row.get("cot"):
            out["cot"] = row["cot"]
        out["conversations"] = row["conversations"]
        out_rows.append(out)

    if args.dry_run:
        print("rows=%d gpt=%d bubbles=%d cot=%d" % (
            len(out_rows), report["gpt_replies"], report["assistant_turns"],
            report["cot"]["count"]))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    write_jsonl(args.out, out_rows)
    write_json(args.report, report)
    write_json(ID_MAP, id_map)
    picked, seen = [], set()
    for row in out_rows:
        if row["scene"] in seen:
            continue
        seen.add(row["scene"])
        picked.append(row)
        if len(picked) == 5:
            break
    write_jsonl(args.samples_out, picked)
    print("wrote %s rows=%d gpt=%d cot=%d" % (
        args.out, len(out_rows), report["gpt_replies"], report["cot"]["count"]))


if __name__ == "__main__":
    main()
