#!/usr/bin/env python3
"""Emit CoT input JSONL from accepted rewrite/new rows.

For each accepted training row, build context before the final gpt, plus
last_human and last_bubbles. Reads only; writes to stdout or --out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCEPTED = os.path.join(ROOT, "distill", "accepted")
LEGACY = os.path.join(ROOT, "distill", "source", "legacy_train.jsonl")
FIXES = os.path.join(ROOT, "distill", "review", "fixes.jsonl")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_wechat import apply_fixes  # noqa: E402


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def source_turns(row):
    return [(m["from"], m["value"]) for m in row["conversations"] if m["from"] != "system"]


def pairs_for(row, kind, legacy):
    if kind == "rewrite":
        src = legacy[row["origin_id"]]
        st = source_turns(src)
        src_humans = [v for r, v in st if r == "human"]
        for idx, turn in enumerate(row["turns"]):
            yield turn.get("human", src_humans[idx]), turn["bubbles"]
    else:
        for turn in row["turns"]:
            yield turn["human"], turn["bubbles"]


def make_input(row, kind, legacy):
    pairs = list(pairs_for(row, kind, legacy))
    last_human, last_bubbles = pairs[-1]
    context = []
    for human, bubbles in pairs[:-1]:
        context.append({"role": "human", "text": human})
        context.append({"role": "assistant", "text": "\n\n".join(bubbles)})
    return {
        "id": row["origin_id"],
        "context": context,
        "last_human": last_human,
        "last_bubbles": last_bubbles,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--ids", default=None,
                    help="optional file with one id per line")
    args = ap.parse_args()

    legacy = {r["id"]: r for r in read_jsonl(LEGACY)}
    accepted = []
    for kind in ("rewrite", "new"):
        accepted += [dict(r, _kind=kind)
                     for r in read_jsonl(os.path.join(ACCEPTED, kind + ".jsonl"))]
    fixes = list(read_jsonl(FIXES)) if os.path.exists(FIXES) else []
    apply_fixes(accepted, fixes)
    rows = [make_input(r, r["_kind"], legacy) for r in accepted]
    if args.ids:
        wanted = {line.strip() for line in open(args.ids, encoding="utf-8")
                  if line.strip()}
        rows = [r for r in rows if r["id"] in wanted]
    rows.sort(key=lambda r: r["id"])
    text = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
    if args.out:
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        os.replace(tmp, args.out)
    else:
        print(text)
    print("rows=%d" % len(rows), file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
