#!/usr/bin/env python3
"""Merge regenerated CoT rows into the existing CoT file."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_wechat import validate_cot  # noqa: E402


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    ids = {line.strip() for line in open(args.ids, encoding="utf-8") if line.strip()}
    old = {r["id"]: r["cot"] for r in read_jsonl(args.old)}
    new = {}
    for row in read_jsonl(args.new):
        rid, cot = row["id"], row.get("cot")
        if rid not in ids:
            raise SystemExit(f"unexpected new cot id: {rid}")
        if rid in new:
            raise SystemExit(f"duplicate new cot id: {rid}")
        errs = validate_cot(cot)
        if errs:
            raise SystemExit(f"bad cot {rid}: {errs}")
        new[rid] = cot.strip()
    missing = ids - set(new)
    if missing:
        raise SystemExit(f"missing new cot: {sorted(missing)[:5]}")

    out = []
    replaced = 0
    for rid, cot in old.items():
        if rid in new:
            out.append({"id": rid, "cot": new[rid]})
            replaced += 1
        else:
            out.append({"id": rid, "cot": cot})
    added = 0
    for rid in sorted(ids - set(old)):
        out.append({"id": rid, "cot": new[rid]})
        added += 1
    ids_out = [r["id"] for r in out]
    if len(ids_out) != len(set(ids_out)):
        raise SystemExit("duplicate ids in merged cot")
    write_jsonl(args.out, out)
    report = {"old": len(old), "new": len(new), "replaced": replaced,
              "added": added, "final": len(out),
              "min": min(len(r["cot"]) for r in out),
              "avg": round(sum(len(r["cot"]) for r in out) / len(out), 1),
              "max": max(len(r["cot"]) for r in out)}
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
