#!/usr/bin/env python3
"""Emit scale rewrite chunks from legacy, excluding pilot and existing chunks.

  python tools/make_scale_input.py --count
  python tools/make_scale_input.py --source nekoqa --chunk 50 --index 0 --out ...
  python tools/make_scale_input.py --source ab --chunk 10 --index 0 --out ...
"""
from __future__ import annotations

import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "distill", "source", "legacy_train.jsonl")
PILOT_INPUTS = (
    os.path.join(ROOT, "distill", "batches", "rewrite_b001.in.jsonl"),
    os.path.join(ROOT, "distill", "batches", "rewrite_b002.in.jsonl"),
)
SCALE_DIR = os.path.join(ROOT, "distill", "batches", "scale")
LONG_KW = ("诗", "写诗", "介绍", "如何", "怎样", "为什么")
DEFAULT_CHUNK = {"nekoqa": 50, "ab": 10, "all": 10}


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def turns(row):
    return [(m["from"], m["value"]) for m in row["conversations"] if m["from"] != "system"]


def make_row(row):
    t = turns(row)
    humans = [v for r, v in t if r == "human"]
    gpts = [v for r, v in t if r == "gpt"]
    long_hint = (row["source"] == "nekoqa"
                 and any(k in humans[0] for k in LONG_KW)
                 and max(len(g) for g in gpts) >= 150)
    return {
        "origin_id": row["id"],
        "source": row["source"],
        "scene": row["scene"],
        "turns": [{"human": h, "gpt": g} for h, g in zip(humans, gpts)],
        "gpt_turns": len(gpts),
        "human_max": max(len(h) for h in humans),
        "gpt_min": min(len(g) for g in gpts),
        "gpt_max": max(len(g) for g in gpts),
        "user_changed_hint": max(len(h) for h in humans) > 30,
        "target_profile": "long" if long_hint else "short",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("nekoqa", "ab", "all"), default="all")
    ap.add_argument("--chunk", type=int, default=0)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--count", action="store_true")
    args = ap.parse_args()

    excluded = set()
    for path in PILOT_INPUTS:
        excluded.update(r["origin_id"] for r in read_jsonl(path))
    for path in glob.glob(os.path.join(SCALE_DIR, "*.in.jsonl")):
        excluded.update(r["origin_id"] for r in read_jsonl(path))

    rows = [r for r in read_jsonl(LEGACY) if r["id"] not in excluded]
    if args.source == "nekoqa":
        rows = [r for r in rows if r["source"] == "nekoqa"]
    elif args.source == "ab":
        rows = [r for r in rows if r["source"] != "nekoqa"]
    rows.sort(key=lambda r: r["id"])

    chunk = args.chunk or DEFAULT_CHUNK[args.source]
    chunks = (len(rows) + chunk - 1) // chunk
    if args.count:
        print(json.dumps({"source": args.source, "remaining": len(rows),
                          "chunk": chunk, "chunks": chunks}))
        return
    if not 0 <= args.index < chunks:
        raise SystemExit(f"index out of range: {args.index} / {chunks}")
    batch = rows[args.index * chunk:(args.index + 1) * chunk]
    text = "\n".join(json.dumps(make_row(r), ensure_ascii=False,
                                separators=(",", ":")) for r in batch)
    if args.out:
        tmp = args.out + ".tmp"
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        os.replace(tmp, args.out)
    else:
        print(text)
    print(json.dumps({"source": args.source, "index": args.index,
                      "rows": len(batch), "ids": [r["id"] for r in batch]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
