#!/usr/bin/env python3
"""Emit pilot rewrite input JSONL from the frozen legacy train.jsonl.

Reads only; writes to stdout.
  python tools/make_pilot_input.py --batch b001 > distill/batches/rewrite_b001.in.jsonl
  python tools/make_pilot_input.py --batch b002 > distill/batches/rewrite_b002.in.jsonl
"""
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "distill", "source", "legacy_train.jsonl")
LONG_KW = ("诗", "写", "为什么", "建议", "介绍", "如何", "怎样",
           "意义", "人生", "死亡", "宇宙", "星星", "月亮")

B001 = """cg_0073 cg_0458 cg_0053 cg_0086 cg_0124 cg_0077 cg_0485 cg_0112 cg_0230 cg_1429
cg_1442 cg_2493 cg_0520 cg_0174 cg_0222 cg_0586 cg_0045 cg_0060 cg_0164 cg_0255
cg_0057 cg_0022 cg_0090 cg_0021 cg_0079 cg_0001 cg_0003 cg_0006 cg_0009 cg_0011
cg_0014 cg_0017 cg_0024 cg_0029 cg_0033 cg_0015 cg_0023 cg_0036 cg_0044 cg_0050
cg_0012 cg_0041 cg_0065 cg_0171 cg_0192 cg_0020 cg_0039 cg_0042 cg_0046 cg_0054""".split()
B002 = """cg_0038 cg_0403 cg_0089 cg_0994 cg_0083 cg_0233 cg_0499 cg_1654 cg_0253 cg_0198
cg_0803 cg_3168 cg_0004 cg_0074 cg_0118 cg_0221 cg_0512 cg_0030 cg_0135 cg_0127
cg_0110 cg_0027 cg_0051 cg_0055 cg_0008 cg_0002 cg_0005 cg_0007 cg_0010 cg_0013
cg_0016 cg_0018 cg_0028 cg_0031 cg_0034 cg_0019 cg_0025 cg_0037 cg_0049 cg_0052
cg_0032 cg_0048 cg_0067 cg_0190 cg_0202 cg_0035 cg_0040 cg_0043 cg_0047 cg_0056""".split()
BATCHES = {"b001": B001, "b002": B002}


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def turns(row):
    return [(m["from"], m["value"]) for m in row["conversations"] if m["from"] != "system"]


def make_row(row, batch):
    t = turns(row)
    humans = [v for r, v in t if r == "human"]
    gpts = [v for r, v in t if r == "gpt"]
    return {
        "origin_id": row["id"],
        "batch": batch,
        "source": row["source"],
        "scene": row["scene"],
        "turns": [{"human": h, "gpt": g} for h, g in zip(humans, gpts)],
        "gpt_turns": len(gpts),
        "human_max": max(len(h) for h in humans),
        "gpt_min": min(len(g) for g in gpts),
        "gpt_max": max(len(g) for g in gpts),
        "user_changed_hint": max(len(h) for h in humans) > 30,
        "_long_score": (
            any(k in humans[0] for k in LONG_KW),
            max(len(g) for g in gpts),
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=("b001", "b002", "both"), default="both")
    ap.add_argument("--legacy", default=LEGACY)
    args = ap.parse_args()

    rows = {r["id"]: r for r in read_jsonl(args.legacy)}
    names = ("b001", "b002") if args.batch == "both" else (args.batch,)

    for name in names:
        ids = BATCHES[name]
        missing = [i for i in ids if i not in rows]
        if missing:
            raise SystemExit(f"{name}: missing legacy ids {missing[:5]}")
        batch = [make_row(rows[i], name) for i in ids]

        nekoqa = [r for r in batch if r["source"] == "nekoqa"]
        nekoqa.sort(key=lambda r: r["_long_score"], reverse=True)
        long_ids = {r["origin_id"] for r in nekoqa[:5]}

        for r in batch:
            r["target_profile"] = "long" if r["origin_id"] in long_ids else "short"
            r.pop("_long_score", None)
            print(json.dumps(r, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
