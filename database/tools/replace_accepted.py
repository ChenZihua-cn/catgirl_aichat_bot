#!/usr/bin/env python3
"""Replace selected accepted rows with a repaired output file.

  python tools/replace_accepted.py --kind rewrite \
    --new batches/chunks/rewrite_b001_c01_v2.out.jsonl \
    --new batches/chunks/rewrite_b001_c02_v2.out.jsonl \
    --ids /tmp/replace_ids.txt
"""
from __future__ import annotations

import argparse
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("rewrite", "new"), required=True)
    ap.add_argument("--new", action="append", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--accepted-dir", default=os.path.join(ROOT, "distill", "accepted"))
    args = ap.parse_args()

    ids = {line.strip() for line in open(args.ids, encoding="utf-8") if line.strip()}
    path = os.path.join(args.accepted_dir, args.kind + ".jsonl")
    original = list(read_jsonl(path))
    replaced = {}
    for new_path in args.new:
        for row in read_jsonl(new_path):
            rid = row.get("origin_id")
            if rid not in ids:
                raise SystemExit(f"unexpected repaired id: {rid}")
            if rid in replaced:
                raise SystemExit(f"duplicate repaired id: {rid}")
            replaced[rid] = row
    missing = ids - set(replaced)
    if missing:
        raise SystemExit(f"missing repaired ids: {sorted(missing)[:5]}")
    kept = [r for r in original if r.get("origin_id") not in ids]
    if len(kept) + len(replaced) != len(original):
        raise SystemExit("row count mismatch")
    shutil.copy(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for row in kept:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        for rid in sorted(replaced):
            f.write(json.dumps(replaced[rid], ensure_ascii=False,
                               separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    print(f"replaced {len(replaced)} rows in {path}; kept {len(kept)}")


if __name__ == "__main__":
    main()
