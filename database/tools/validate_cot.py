#!/usr/bin/env python3
"""Validate and merge CoT outputs for the pilot/final corpus."""
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


def write_json(path, obj):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    expected = [r["id"] for r in read_jsonl(args.expected)]
    seen, accepted, rejected = set(), {}, []
    for path in args.inputs:
        for row in read_jsonl(path):
            rid, cot = row.get("id"), row.get("cot")
            if rid in seen:
                rejected.append({"id": rid, "reasons": ["duplicate"]})
                continue
            seen.add(rid)
            if rid not in set(expected):
                rejected.append({"id": rid, "reasons": ["extra_id"]})
                continue
            errs = validate_cot(cot)
            if errs:
                rejected.append({"id": rid, "reasons": errs})
            else:
                accepted[rid] = cot.strip()
    missing = [rid for rid in expected if rid not in accepted]
    merged = [{"id": rid, "cot": accepted[rid]} for rid in expected if rid in accepted]
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for row in merged:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, args.out)
    report = {
        "expected": len(expected),
        "accepted": len(merged),
        "rejected": len(rejected),
        "missing": missing[:30],
        "rejected_rows": rejected[:30],
        "min": min((len(r["cot"]) for r in merged), default=0),
        "avg": round(sum(len(r["cot"]) for r in merged) / max(1, len(merged)), 1),
        "max": max((len(r["cot"]) for r in merged), default=0),
    }
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
