#!/usr/bin/env python3
"""Validate one pilot/scale batch against the frozen bubble rules.

  python tools/validate_batch.py --kind rewrite \
    --input distill/batches/rewrite_b001.in.jsonl \
    --output distill/batches/rewrite_b001.out.jsonl \
    --report distill/batches/rewrite_b001.report.json

  python tools/validate_batch.py --kind new \
    --input distill/batches/new_b001.in.jsonl \
    --output distill/batches/new_b001.out.jsonl \
    --report distill/batches/new_b001.report.json

Does not write accepted data unless --accept is passed.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_wechat import CAT_WORDS, validate_bubbles, validate_human, validate_new  # noqa: E402
from build_wechat import is_emoji  # noqa: E402


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path, obj):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def append_jsonl(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def validate_rewrite_out(out, inp):
    errs = []
    if out.get("origin_id") != inp["origin_id"]:
        errs.append("origin_id")
    if out.get("status") not in ("ok", "skip"):
        return errs + ["status"]
    if out["status"] == "skip":
        if not out.get("reason"):
            errs.append("skip_reason")
        return errs
    turns = out.get("turns")
    if not isinstance(turns, list) or len(turns) != len(inp["turns"]):
        return errs + ["turns"]
    for idx, (ot, it) in enumerate(zip(turns, inp["turns"])):
        if not isinstance(ot, dict):
            errs.append((idx, "type"))
            continue
        errs += [(idx, e) for e in validate_bubbles(
            ot.get("bubbles"), ot.get("profile", "short"))]
        if "human" in ot:
            if not ot.get("user_changed"):
                errs.append((idx, "human_without_flag"))
            errs += [(idx, e) for e in validate_human(ot["human"])]
            if len(ot["human"]) > len(it["human"]):
                errs.append((idx, "human_longer"))
        elif ot.get("user_changed"):
            errs.append((idx, "flag_without_human"))
    return errs


def validate_new_out(out, seed):
    errs = list(validate_new(out, seed))
    turns = out.get("turns")
    if not isinstance(turns, list):
        return errs
    if len(turns) != seed["target_turns"]:
        errs.append(("target_turns", len(turns)))
    idx = seed["callback_turn"] - 1
    if not 0 <= idx < len(turns):
        errs.append("callback_turn_out_of_range")
    else:
        ref = turns[idx].get("callback_ref")
        if not isinstance(ref, dict) or ref.get("key") != seed["callback_key"]:
            errs.append("seed_callback_missing")
    return errs


def metrics(accepted, kind):
    per_turn = [turn for row in accepted for turn in row.get("turns", [])]
    bubbles = [b for turn in per_turn for b in turn.get("bubbles", [])]
    lengths = [len(b) for b in bubbles]
    turn_lengths = [len("\n\n".join(turn.get("bubbles", []))) for turn in per_turn]
    hist = collections.Counter(len(turn.get("bubbles", [])) for turn in per_turn)
    return {
        "assistant_turns": len(per_turn),
        "bubbles": len(bubbles),
        "bubble_count": {str(k): v for k, v in sorted(hist.items())},
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
        "single_bubble_share": round(hist.get(1, 0) / max(1, len(per_turn)), 4),
        "multi_bubble_share": round(
            sum(v for k, v in hist.items() if k > 1) / max(1, len(per_turn)), 4),
        "emoji_turn_share": round(
            sum(1 for turn in per_turn if any(
                is_emoji(ch) for b in turn.get("bubbles", []) for ch in b))
            / max(1, len(per_turn)), 4),
        "question_turn_share": round(
            sum(1 for turn in per_turn
                if turn.get("bubbles") and re.search(
                    r"[？?]\s*$|[吗呢嘛]\s*$", turn["bubbles"][-1]))
            / max(1, len(per_turn)), 4),
        "cat_turn_share": round(
            sum(1 for turn in per_turn if any(
                w in b for b in turn.get("bubbles", []) for w in CAT_WORDS))
            / max(1, len(per_turn)), 4),
        "user_changed": sum(
            1 for row in accepted for turn in row.get("turns", [])
            if turn.get("user_changed")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("rewrite", "new"), required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--accept", action="store_true")
    ap.add_argument("--accepted-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "distill", "accepted"))
    ap.add_argument("--rejected", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "distill", "review", "rejected.jsonl"))
    ap.add_argument("--new-start", type=int, default=1,
                    help="first origin_id number for accepted new sessions")
    args = ap.parse_args()

    inputs = {r["origin_id" if args.kind == "rewrite" else "seed_id"]: r
              for r in read_jsonl(args.input)}
    outputs = list(read_jsonl(args.output))
    seen, accepted, rejected = set(), [], []
    for out in outputs:
        key = out.get("origin_id" if args.kind == "rewrite" else "seed_id")
        if key in seen:
            rejected.append({"id": key, "reasons": ["duplicate"]})
            continue
        seen.add(key)
        if key not in inputs:
            rejected.append({"id": key, "reasons": ["extra_id"]})
            continue
        errs = (validate_rewrite_out(out, inputs[key]) if args.kind == "rewrite"
                else validate_new_out(out, inputs[key]))
        if out.get("status") == "skip":
            rejected.append({"id": key, "reasons": ["skip: " + str(out.get("reason", ""))]})
        elif errs:
            rejected.append({"id": key, "reasons": errs[:12]})
        else:
            accepted.append(out)

    missing = [k for k in inputs if k not in seen]
    report = {
        "kind": args.kind,
        "input": args.input,
        "output": args.output,
        "input_count": len(inputs),
        "output_count": len(outputs),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "pass_rate": round(len(accepted) / max(1, len(inputs)), 4),
        "missing_ids": missing[:20],
        "accepted_ids": [r.get("origin_id" if args.kind == "rewrite" else "seed_id")
                         for r in accepted],
        "rejected": rejected[:30],
        **metrics(accepted, args.kind),
    }
    write_json(args.report, report)

    if args.accept:
        if args.kind == "rewrite":
            append_jsonl(os.path.join(args.accepted_dir, "rewrite.jsonl"), accepted)
        else:
            for i, out in enumerate(accepted, args.new_start):
                out = dict(out)
                out["origin_id"] = "new_%04d" % i
                append_jsonl(os.path.join(args.accepted_dir, "new.jsonl"), [out])
    append_jsonl(args.rejected, [
        {"kind": args.kind, "id": r["id"], "reasons": r["reasons"]}
        for r in rejected
    ])
    print(json.dumps({k: report[k] for k in (
        "kind", "input_count", "output_count", "accepted_count",
        "rejected_count", "pass_rate", "missing_ids")}, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in (
        "assistant_turns", "bubbles", "bubble_count", "single_bubble_share",
        "multi_bubble_share", "emoji_turn_share", "question_turn_share",
        "cat_turn_share", "user_changed")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
