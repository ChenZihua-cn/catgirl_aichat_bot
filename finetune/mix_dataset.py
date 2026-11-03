"""Mixed image-text + persona-text pipeline for Qwen3.5-4B-Base LoRA SFT.

Normalises the local catgirl corpora and the downloaded image-text shards into one
Qwen3.5 encoding (input_ids / labels / pixel_values / image_grid_thw /
mm_token_type_ids) with assistant-only loss.

Measured facts this file relies on:
  * the processor text kwarg is "text="; "texts=" is silently ignored.
  * im_start, im_end and image_pad are single tokens (248045, 248046, 248056), so a
    turn body tokenises identically whether or not the template wrapper is present.
  * the vision block is vision_start + N x image_pad + vision_end with
    N = grid_t * grid_h * grid_w / merge_size**2.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random

import pyarrow.parquet as pq
import torch
from PIL import Image
from transformers import AutoProcessor

MODEL_DIR = "/home/labubu/30856/Model/Qwen3.5-4B-Base"
DB = "/home/labubu/30856/Code/catgirl_aichat_bot/database"
DS = "/home/labubu/30856/Model/datasets"

# The literal token strings are assembled from fragments: raw forms break tool-side JSON parsing.
_L, _R = "<", ">"
IM_START = _L + "|im_start|" + _R
IM_END = _L + "|im_end|" + _R
IMAGE_PAD = _L + "|image_pad|" + _R
VISION_START = _L + "|vision_start|" + _R
VISION_END = _L + "|vision_end|" + _R
IMAGE_MARKERS = (_L + "|image|" + _R, _L + "image" + _R)

# A 2048 ctx is the plan; keep vision tokens cheap so persona replies are not squeezed out.
MIN_PIXELS = 4 * 32 * 32
MAX_PIXELS = 512 * 512

ROLE_MAP = {"human": "user", "user": "user", "gpt": "assistant",
            "assistant": "assistant", "system": "system"}


class Record:
    __slots__ = ("turns", "images", "source", "kind")

    def __init__(self, turns, images=None, source="", kind="text"):
        self.turns = turns          # [{"role":..., "text":...}] with image marker stripped
        self.images = images or []
        self.source = source
        self.kind = kind


def _strip_marker(text):
    for marker in IMAGE_MARKERS:
        text = text.replace(marker, "")
    return text.lstrip("\n")


def _turns_from_conv(conv):
    turns = []
    for t in conv:
        role = ROLE_MAP.get(t.get("from") or t.get("role"))
        val = t.get("value")
        if val is None:
            val = t.get("content")
        if role is None or not isinstance(val, str) or not val.strip():
            continue
        turns.append({"role": role, "text": val})
    return turns


# --------------------------------------------------------------------- text side

def _load_jsonl(path, source):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            conv = obj.get("conversations") or obj.get("messages")
            if not conv:
                continue
            turns = _turns_from_conv(conv)
            if len(turns) >= 2 and turns[-1]["role"] == "assistant":
                cot = obj.get("cot")
                if isinstance(cot, str) and cot.strip():
                    turns[-1]["cot"] = cot.strip()
                yield Record(turns, source=source)


def load_persona(corpus, limit=None):
    path = os.path.join(DB, "train.jsonl") if corpus == "merged" else corpus
    if not os.path.exists(path):
        raise SystemExit(f"unknown text corpus: {corpus}")
    recs = list(_load_jsonl(path, corpus))
    return recs[:limit] if limit else recs


def attach_system(recs, system_text):
    for r in recs:
        if r.turns[0]["role"] != "system":
            r.turns.insert(0, {"role": "system", "text": system_text})
    return recs


# -------------------------------------------------------------------- vision side

def _to_pil(raw):
    if isinstance(raw, Image.Image):
        return raw.convert("RGB")
    if isinstance(raw, dict):
        raw = raw.get("bytes")
    if isinstance(raw, (bytes, bytearray)):
        return Image.open(io.BytesIO(raw)).convert("RGB")
    raise ValueError(f"unsupported image payload: {type(raw)}")


def _rows(path, limit):
    pf = pq.ParquetFile(path)
    got = 0
    for rg in range(pf.num_row_groups):
        if limit and got >= limit:
            return
        for row in pf.read_row_group(rg).to_pylist():
            yield row
            got += 1
            if limit and got >= limit:
                return


def _iter_vlm(path, source, limit):
    """Handles both schemas seen on disk: LLaVA-OneVision (image + conversations)
    and llava-instruct-mix-vsft (images + messages with typed content parts)."""
    for row in _rows(path, limit):
        if "conversations" in row:
            img = row.get("image")
            imgs = [_to_pil(img)] if img else [_to_pil(x) for x in (row.get("images") or [])]
            turns = _turns_from_conv(row["conversations"])
            if imgs and turns and turns[0]["role"] == "user":
                turns[0]["text"] = _strip_marker(turns[0]["text"])
        else:
            imgs = [_to_pil(x) for x in (row.get("images") or [])]
            turns = []
            for m in row.get("messages") or []:
                role = ROLE_MAP.get(m.get("role"))
                parts = m.get("content")
                if role is None:
                    continue
                if isinstance(parts, list):
                    text = "".join(p.get("text") or "" for p in parts if p.get("type") != "image")
                else:
                    text = parts or ""
                if text.strip():
                    turns.append({"role": role, "text": _strip_marker(text)})
        if not imgs or len(turns) < 2 or turns[-1]["role"] != "assistant":
            continue
        yield Record(turns, images=imgs, source=source, kind="image")


IMAGE_SOURCES = (
    ("llava_mix", "llava-instruct-mix-vsft/data/train-00000-of-00020.parquet"),
    ("onevision_wild", "LLaVA-OneVision-Data/llava_wild_4v_12k_filtered/train-00000-of-00002.parquet"),
    ("ureader_cap", "LLaVA-OneVision-Data/ureader_cap/train-00000-of-00019.parquet"),
)


def load_image_text(per_source):
    recs = []
    for source, rel in IMAGE_SOURCES:
        path = os.path.join(DS, rel)
        if not os.path.exists(path):
            print(f"[warn] missing {path}")
            continue
        got = 0
        for r in _iter_vlm(path, source, per_source):
            recs.append(r)
            got += 1
        print(f"[info] {source}: {got} usable rows")
    return recs


# ------------------------------------------------------------------- the persona hook

def persona_hook(record, style=None):
    """TODO(step 2): rewrite image-text answers into the catgirl voice.

    Left identity on purpose: the image-text rows are a retention anchor, and the
    visual grounding in the original answers is what keeps the pathway honest.
    The style transfer needs a decision first (see the Chinese-data question).
    """
    return record


# ---------------------------------------------------------------------- encoding

class Encoder:
    def __init__(self, model_dir=MODEL_DIR):
        self.proc = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        self.tok = self.proc.tokenizer
        self.img_proc = self.proc.image_processor
        self.merge_sq = self.img_proc.merge_size ** 2
        self.ids_im_start = self._ids(IM_START)
        self.ids_im_end_nl = self._ids(IM_END + "\n")
        self.ids_vs = self._ids(VISION_START)
        self.ids_ve = self._ids(VISION_END)
        self.pad_id = self.proc.image_token_id
        self.role_prefix = {r: self._ids(f"{r}\n") for r in ("system", "user", "assistant")}

    def _ids(self, s):
        return self.tok(s, add_special_tokens=False)["input_ids"]

    def encode(self, record, max_len=2048):
        grids = pixel_values = None
        pads = []
        if record.images:
            out = self.img_proc(images=record.images, return_tensors="pt",
                                min_pixels=MIN_PIXELS, max_pixels=MAX_PIXELS)
            grids = out.image_grid_thw
            pixel_values = out.pixel_values
            pads = [int(t * h * w) // self.merge_sq for t, h, w in grids.tolist()]

        ids, labels = [], []
        first_user = next((i for i, t in enumerate(record.turns) if t["role"] == "user"), None)
        for i, turn in enumerate(record.turns):
            role = turn["role"]
            head = self.ids_im_start + self.role_prefix[role]
            cot = turn.get("cot")
            tail = self.ids_im_end_nl
            if role == "assistant" and cot and i == len(record.turns) - 1:
                # Qwen3.5 generation with enable_thinking=true already emits
                # "<|im_start|>assistant\n<think>\n"; only the continuation is
                # supervised, so the opening tag is masked out of the labels.
                think = self._ids("<think>\n")
                body = think + self._ids(cot + "\n</think>\n\n" + turn["text"])
                ids += head + body + tail
                labels += [-100] * (len(head) + len(think)) + body[len(think):] + tail
                continue
            body = []
            if record.images and role == "user" and i == first_user:
                for n in pads:
                    body += self.ids_vs + [self.pad_id] * n + self.ids_ve
            body += self._ids(turn["text"])
            ids += head + body + tail
            if role == "assistant":
                labels += [-100] * len(head) + body + tail
            else:
                labels += [-100] * (len(head) + len(body) + len(tail))

        # turn-granular truncation: a window boundary is the id right after the
        # newline that closes an im_end trailer, so we never cut inside a turn
        nl = self.ids_im_end_nl[-1]
        ends = {im_end + 2 for im_end, tok_id in enumerate(ids)
                if tok_id == self.ids_im_end_nl[0] and ids[im_end + 1] == nl}
        keep = max([0] + [b for b in sorted(ends) if b <= max_len])
        # dropping back to the previous window is required when the only kept
        # assistant turn was the one that did not fit (all -100 labels)
        while keep and all(x == -100 for x in labels[:keep]):
            smaller = [b for b in ends if b < keep]
            if not smaller:
                keep = 0
                break
            keep = max(smaller)
        if keep == 0:
            raise AssertionError(f"row needs {len(ids)} tokens, over ctx {max_len}")
        dropped = keep < len(ids)
        ids, labels = ids[:keep], labels[:keep]

        # the template closes the last assistant turn with a stop token, so training
        # without it never teaches the model where a reply ends; appending it to a
        # truncated row is wrong too, that would train a premature stop
        if not dropped and record.turns[-1]["role"] == "assistant":
            eos = self.tok.eos_token_id
            ids.append(eos)
            labels.append(eos)

        result = {
            "input_ids": torch.tensor(ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.ones(len(ids), dtype=torch.long),
            "mm_token_type_ids": torch.tensor(
                [1 if x == self.pad_id else 0 for x in ids], dtype=torch.long),
        }
        if pixel_values is not None:
            result["pixel_values"] = pixel_values
            result["image_grid_thw"] = grids
            n_pad = int((result["input_ids"] == self.pad_id).sum())
            if n_pad != sum(pads):
                raise AssertionError(f"vision pad count {n_pad} != grid expectation {sum(pads)}")
        if int((result["labels"] != -100).sum()) == 0:
            raise AssertionError("no supervised tokens survived truncation")
        return result


# -------------------------------------------------------------------------- CLI

def build_mixture(args):
    text = load_persona(args.text, args.text_cap)
    if args.with_system:
        path = os.path.join(DB, "system_prompt.txt")
        text = attach_system(text, open(path, encoding="utf-8").read().strip())
    else:
        for r in text:
            if r.turns and r.turns[0]["role"] == "system":
                r.turns = r.turns[1:]
    image = load_image_text(args.image_cap)
    if not image:
        n_img = 0
    else:
        n_img = max(0, min(len(image), int(args.ratio / (1 - args.ratio) * len(text))))
    mixed = [persona_hook(r) for r in image[:n_img]] + text
    random.Random(args.seed).shuffle(mixed)
    return mixed, n_img, len(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="merged", help="merged (database/train.jsonl)")
    ap.add_argument("--text-cap", type=int, default=200)
    ap.add_argument("--image-cap", type=int, default=30)
    ap.add_argument("--ratio", type=float, default=0.34, help="image-text share of mixture")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--with-system", dest="with_system", action="store_true", default=True)
    ap.add_argument("--no-system", dest="with_system", action="store_false")
    args = ap.parse_args()

    enc = Encoder()
    mixed, n_img, n_text = build_mixture(args)
    print(f"[mix] {n_img} image-text + {n_text} persona-text = {len(mixed)} rows "
          f"({n_img / max(1, len(mixed)):.1%} image)")

    ok = truncated = ended = supervised = 0
    fail = {}
    for r in mixed:
        try:
            e = enc.encode(r, args.max_len)
            ok += 1
            if len(e["input_ids"]) == args.max_len:
                truncated += 1
            if e["labels"][-1].item() == enc.tok.eos_token_id:
                ended += 1
            supervised += int((e["labels"] != -100).sum())
        except Exception as exc:
            fail.setdefault(f"{type(exc).__name__}: {exc}", []).append(r.source)
    print(f"[encode] ok={ok} truncated_at_{args.max_len}={truncated} "
          f"terminal_stop_supervised={ended}/{ok} supervised_tokens={supervised}")
    for why, srcs in fail.items():
        print(f"[fail] {len(srcs)} rows: {why}  e.g. {srcs[:3]}")

    sample = next((r for r in mixed if r.kind == "image"), None)
    if sample:
        e = enc.encode(sample, args.max_len)
        sup = int((e["labels"] != -100).sum())
        print("\n[sample image row]", sample.source,
              "len", tuple(e["input_ids"].shape),
              "supervised", sup,
              "pixel_values", tuple(e["pixel_values"].shape),
              "grid", e["image_grid_thw"].tolist(),
              f"pads={int((e['input_ids']==enc.pad_id).sum())}")
        ans = e["labels"][e["labels"] != -100]
        print("[supervised text decodes to]",
              enc.tok.decode(ans, skip_special_tokens=False)[:220])


if __name__ == "__main__":
    main()
